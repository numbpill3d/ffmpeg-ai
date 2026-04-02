"""Orchestrates the full Short generation pipeline."""
import asyncio
import random
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich import box

from .ui.display import print_stage, print_success, print_info, print_error
from .ui.widgets import pipeline_progress, stats_table
from .ai.openrouter import generate_script, FREE_MODELS
from .ai.images import generate_images, load_user_images, USER_IMAGES_DIR
from .ai.tts import synthesize_segments, DEFAULT_VOICE
from .video.composer import (
    image_to_video, concat_with_transitions, concat_audio,
    merge_audio, mix_music, burn_captions, final_encode, get_audio_duration,
    MOTION_STYLES,
)
from .video.captions import audio_to_ass
from .video.shorts import clamp_duration

console = Console()


async def run_pipeline(
    topic: str,
    output_path: Path,
    duration: int = 45,
    model: str = FREE_MODELS[0],
    voice: str = DEFAULT_VOICE,
    dry_run: bool = False,
    images_dir: Optional[Path] = None,
    use_ai_images: bool = True,
    image_providers: Optional[list[str]] = None,
    music_path: Optional[Path] = None,
) -> Path:
    """
    images_dir:       if set, use images from this directory (skips AI generation).
    use_ai_images:    if False and no images_dir, uses PIL placeholder images.
    image_providers:  ordered list of AI providers to try: "pollinations", "huggingface".
    music_path:       optional background music file; auto-ducked under narration.
    """
    start_time = time.time()

    with tempfile.TemporaryDirectory(prefix="ffmpeg_ai_") as tmp:
        tmp_dir = Path(tmp)

        # ── 1. Script ────────────────────────────────────────────────────────
        print_stage("SCRIPT", f"model: {model.split('/')[1]}")
        with pipeline_progress("Generating script") as prog:
            task = prog.add_task("Asking AI...", total=1)
            script = await generate_script(topic, duration=duration, model=model)
            prog.update(task, completed=1)

        console.print(Panel(
            stats_table({
                "title": script.get("title", ""),
                "hook": script.get("hook", ""),
                "segments": str(len(script.get("segments", []))),
                "images": str(len(script.get("image_prompts", []))),
            }),
            title="[cyan]Script[/]", border_style="bright_black", box=box.ROUNDED,
        ))

        if dry_run:
            print_info("Dry run — stopping after script generation.")
            return output_path

        segments = script["segments"]
        image_prompts = script.get("image_prompts", [s.get("visual", topic) for s in segments])

        # ── 2. TTS ───────────────────────────────────────────────────────────
        print_stage("TTS", f"voice: {voice.split('-')[-1]}")
        tts_dir = tmp_dir / "tts"
        with pipeline_progress("Synthesizing voiceover") as prog:
            task = prog.add_task("edge-tts...", total=len(segments) + 2)

            hook_audio = tts_dir / "hook.mp3"
            tts_dir.mkdir(parents=True, exist_ok=True)
            from .ai.tts import synthesize
            await synthesize(script.get("hook", ""), hook_audio, voice=voice)
            prog.advance(task)

            seg_audios = await synthesize_segments(segments, tts_dir, voice=voice)
            prog.advance(task, advance=len(segments))

            cta_audio = tts_dir / "cta.mp3"
            await synthesize(script.get("cta", ""), cta_audio, voice=voice)
            prog.advance(task)

        all_audios = [hook_audio] + list(seg_audios) + [cta_audio]
        combined_audio = tmp_dir / "narration.mp3"
        concat_audio(all_audios, combined_audio)
        total_dur = clamp_duration(get_audio_duration(combined_audio))
        print_success(f"Narration: {total_dur:.1f}s")

        # ── 3. Images ────────────────────────────────────────────────────────
        img_dir = tmp_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        n = len(image_prompts)

        if images_dir is not None:
            print_stage("IMAGES", f"user images from {images_dir}")
            src_paths = load_user_images(images_dir, n)
            images = []
            for i, src in enumerate(src_paths):
                dst = img_dir / f"frame_{i:03d}{src.suffix.lower()}"
                shutil.copy2(src, dst)
                images.append(dst)
            print_success(f"Loaded {len(images)} user images")

        elif use_ai_images:
            providers = image_providers or ["pollinations", "huggingface"]
            provider_label = " → ".join(providers)
            print_stage("IMAGES", f"{n} frames  [{provider_label}]")
            with pipeline_progress("Generating images") as prog:
                task = prog.add_task("Generating...", total=n)
                images = await generate_images(
                    image_prompts, img_dir,
                    progress=prog, task_id=task,
                    providers=providers,
                )
            print_success(f"Generated {len(images)} images")

        else:
            print_stage("IMAGES", "placeholder mode (AI disabled)")
            from .ai.images import _make_placeholder
            images = [
                _make_placeholder(p, img_dir / f"frame_{i:03d}.jpg")
                for i, p in enumerate(image_prompts)
            ]
            print_success(f"Created {len(images)} placeholder images")

        # ── 4. Video clips ───────────────────────────────────────────────────
        print_stage("VIDEO", "image → video clips  [varied Ken Burns + xfade transitions]")
        clip_dir = tmp_dir / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        per_img_dur = total_dur / len(images)

        # Shuffle motion styles — no two adjacent clips use the same motion
        motions = _pick_motions(len(images))

        with pipeline_progress("Rendering clips") as prog:
            task = prog.add_task("ffmpeg...", total=len(images))
            clips = []
            clip_durations = []
            for i, img in enumerate(images):
                clip = image_to_video(
                    img, per_img_dur,
                    clip_dir / f"clip_{i:03d}.mp4",
                    motion=motions[i],
                )
                clips.append(clip)
                clip_durations.append(per_img_dur)
                prog.advance(task)

        raw_video = tmp_dir / "raw.mp4"
        concat_with_transitions(clips, clip_durations, raw_video)
        with_audio = tmp_dir / "with_audio.mp4"
        merge_audio(raw_video, combined_audio, with_audio)

        # ── 5. Captions ──────────────────────────────────────────────────────
        print_stage("CAPTIONS", "faster-whisper  [word-level karaoke]")
        ass_path = tmp_dir / "captions.ass"
        with pipeline_progress("Transcribing audio") as prog:
            task = prog.add_task("whisper (base)...", total=1)
            subtitle_path = audio_to_ass(combined_audio, ass_path)
            prog.update(task, completed=1)

        captioned = tmp_dir / "captioned.mp4"
        burn_captions(with_audio, subtitle_path, captioned)

        # ── 6. Background music ──────────────────────────────────────────────
        pre_encode = captioned
        if music_path is not None and music_path.is_file():
            print_stage("MUSIC", f"mixing {music_path.name}  [sidechain ducking]")
            with pipeline_progress("Mixing music") as prog:
                task = prog.add_task("ffmpeg...", total=1)
                with_music = tmp_dir / "with_music.mp4"
                mix_music(captioned, music_path, with_music)
                prog.update(task, completed=1)
            pre_encode = with_music
            print_success("Music mixed with auto-ducking")

        # ── 7. Final encode ──────────────────────────────────────────────────
        print_stage("EXPORT", f"→ {output_path.name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with pipeline_progress("Final encode") as prog:
            task = prog.add_task("YouTube Shorts spec...", total=1)
            final_encode(pre_encode, output_path)
            prog.update(task, completed=1)

    elapsed = time.time() - start_time
    img_source = (
        str(images_dir) if images_dir
        else ("AI (" + ", ".join(image_providers or ["pollinations", "huggingface"]) + ")")
        if use_ai_images else "placeholder"
    )
    console.print(Panel(
        stats_table({
            "output": str(output_path.resolve()),
            "duration": f"{total_dur:.1f}s",
            "elapsed": f"{elapsed:.0f}s",
            "model": model,
            "voice": voice,
            "images": img_source,
            "music": music_path.name if music_path else "none",
        }),
        title="[bold green]Done[/]", border_style="green", box=box.ROUNDED,
    ))
    return output_path


def _pick_motions(n: int) -> list[str]:
    """Return n motion styles with no two adjacent identical styles."""
    if n == 0:
        return []
    styles = MOTION_STYLES.copy()
    result = [random.choice(styles)]
    for _ in range(n - 1):
        remaining = [s for s in styles if s != result[-1]]
        result.append(random.choice(remaining))
    return result
