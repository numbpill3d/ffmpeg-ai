"""Orchestrates the full Short generation pipeline."""
import asyncio
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich import box

from .ui.display import console
from .ui.widgets import PipelineTracker, stats_table
from .ai.openrouter import generate_script, FREE_MODELS
from .ai.images import generate_images, load_user_images, USER_IMAGES_DIR
from .ai.tts import synthesize_segments, synthesize, DEFAULT_VOICE
from .video.composer import (
    image_to_video, concat_with_transitions, concat_audio,
    merge_audio, mix_music, burn_captions, final_encode, get_audio_duration,
    detect_beats, snap_to_beats, extract_thumbnail,
    MOTION_STYLES,
)
from .video.captions import audio_to_ass
from .video.shorts import clamp_duration

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"


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
    script_path: Optional[Path] = None,
    edit_script: bool = False,
    fresh: bool = False,
    quiet: bool = False,
    thumbnail: bool = True,
    style: Optional[str] = None,
    caption_style: str = "karaoke",
) -> Path:
    """
    images_dir:       use images from this directory instead of AI generation.
    use_ai_images:    if False and no images_dir, uses PIL placeholder images.
    image_providers:  ordered list of AI providers: "pollinations", "huggingface".
    music_path:       optional background music file; auto-ducked under narration.
    script_path:      load script JSON from file instead of calling LLM.
    edit_script:      open generated script in $EDITOR before rendering.
    fresh:            ignore all cached job data and start from scratch.
    quiet:            suppress live TUI — one line per stage to stdout.
    thumbnail:        extract a thumbnail JPEG alongside the output file.
    style:            tone preset: educational, dramatic, listicle, documentary.
    caption_style:    karaoke, plain, or bold-center.
    """
    start_time = time.time()

    job_dir = _JOB_CACHE / _slug(topic)
    if fresh:
        shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    n_images_target = max(12, int(duration / 2.2))

    stages = ["SCRIPT", "TTS", "IMAGES", "VIDEO", "CAPTIONS"]
    if music_path and music_path.is_file():
        stages.append("MUSIC")
    stages.append("EXPORT")

    with PipelineTracker(stages, quiet=quiet) as tracker:

        # ── 1. Script ────────────────────────────────────────────────────────
        script_cache = job_dir / "script.json"

        if script_path is not None:
            script = json.loads(Path(script_path).read_text())
            n_s = len(script.get("segments", []))
            n_i = len(script.get("image_prompts", []))
            tracker.complete("SCRIPT", f"{n_s} segs  {n_i} images  (loaded)", cached=True)
        elif not fresh and script_cache.exists():
            script = json.loads(script_cache.read_text())
            n_s = len(script.get("segments", []))
            n_i = len(script.get("image_prompts", []))
            tracker.complete("SCRIPT", f"{n_s} segs  {n_i} images", cached=True)
        else:
            model_short = model.split("/")[-1]
            tracker.start("SCRIPT", f"model: {model_short}")
            script = await generate_script(
                topic, duration=duration, model=model,
                n_images=n_images_target, style=style,
            )
            script_cache.write_text(json.dumps(script, indent=2))
            n_s = len(script.get("segments", []))
            n_i = len(script.get("image_prompts", []))
            tracker.complete("SCRIPT", f"{n_s} segs  {n_i} images")

        tracker.print(Panel(
            stats_table({
                "title":    script.get("title", ""),
                "hook":     script.get("hook", "")[:80],
                "segments": str(len(script.get("segments", []))),
                "images":   str(len(script.get("image_prompts", []))),
            }),
            title="[cyan]script[/]", border_style="bright_black", box=box.ROUNDED,
        ))

        if edit_script:
            edit_file = job_dir / "script_edit.json"
            edit_file.write_text(json.dumps(script, indent=2))
            if tracker._live:
                tracker._live.stop()
            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, str(edit_file)])
            script = json.loads(edit_file.read_text())
            script_cache.write_text(json.dumps(script, indent=2))
            if tracker._live:
                tracker._live.start()

        if dry_run:
            skip = [s for s in stages if s != "SCRIPT"]
            for s in skip:
                tracker.complete(s, "skipped (dry run)")
            return output_path

        segments = script["segments"]
        image_prompts = script.get("image_prompts", [s.get("visual", topic) for s in segments])
        n = len(image_prompts)
        providers = image_providers or ["pollinations", "huggingface"]

        # ── 2+3. TTS + Images (parallel) ─────────────────────────────────────
        tts_dir        = job_dir / "tts"
        img_dir        = job_dir / "images"
        combined_audio = job_dir / "narration.mp3"

        tracker.start("TTS",    f"voice: {voice.split('-')[-1]}")
        tracker.start("IMAGES", f"{n} frames")
        tracker.set_image_count(n)

        async def _do_tts() -> tuple[Path, float]:
            if not fresh and combined_audio.exists():
                dur = clamp_duration(await asyncio.to_thread(get_audio_duration, combined_audio))
                tracker.complete("TTS", f"{dur:.1f}s", cached=True)
                return combined_audio, dur
            tts_dir.mkdir(parents=True, exist_ok=True)
            hook_audio = tts_dir / "hook.mp3"
            await synthesize(script.get("hook", ""), hook_audio, voice=voice)
            seg_audios = await synthesize_segments(segments, tts_dir, voice=voice)
            cta_audio  = tts_dir / "cta.mp3"
            await synthesize(script.get("cta", ""), cta_audio, voice=voice)
            all_a = [hook_audio] + list(seg_audios) + [cta_audio]
            await asyncio.to_thread(concat_audio, all_a, combined_audio)
            dur = clamp_duration(await asyncio.to_thread(get_audio_duration, combined_audio))
            tracker.complete("TTS", f"{dur:.1f}s")
            return combined_audio, dur

        async def _do_images() -> tuple[list[Path], int]:
            if images_dir is not None:
                img_dir.mkdir(parents=True, exist_ok=True)
                src = load_user_images(images_dir, n)
                imgs: list[Path] = []
                for i, s in enumerate(src):
                    dst = img_dir / f"frame_{i:03d}{s.suffix.lower()}"
                    shutil.copy2(s, dst)
                    imgs.append(dst)
                    tracker.image_done(i, False)
                tracker.complete("IMAGES", f"{len(imgs)} user images")
                return imgs, 0

            cached_frames = sorted(img_dir.glob("frame_*.jpg")) if img_dir.is_dir() else []
            if not fresh and len(cached_frames) >= n:
                imgs = cached_frames[:n]
                for i in range(len(imgs)):
                    tracker.image_done(i, False)
                tracker.complete("IMAGES", f"{n} cached", cached=True)
                return imgs, 0

            if not use_ai_images:
                from .ai.images import _make_placeholder
                img_dir.mkdir(parents=True, exist_ok=True)
                imgs = [
                    _make_placeholder(p, img_dir / f"frame_{i:03d}.jpg")
                    for i, p in enumerate(image_prompts)
                ]
                for i in range(len(imgs)):
                    tracker.image_done(i, True)
                tracker.complete("IMAGES", f"{n} placeholders")
                return imgs, n

            img_dir.mkdir(parents=True, exist_ok=True)
            imgs, pc = await generate_images(
                image_prompts, img_dir, providers=providers,
                on_image_done=lambda i, is_pl: tracker.image_done(i, is_pl),
            )
            detail = f"{len(imgs)} images"
            if pc:
                detail += f"  ({pc} placeholder)"
            tracker.complete("IMAGES", detail)
            return imgs, pc

        (combined_audio, total_dur), (images, placeholder_count) = await asyncio.gather(
            _do_tts(), _do_images(),
        )

        # ── 4. Video clips ────────────────────────────────────────────────────
        n = len(images)
        clip_durations = _energy_curve_durations(n, total_dur)

        if music_path is not None and music_path.is_file():
            beats = detect_beats(music_path)
            if beats:
                cut_t: list[float] = []
                t = 0.0
                for d in clip_durations[:-1]:
                    t += d
                    cut_t.append(t)
                snapped = snap_to_beats(cut_t, beats) + [total_dur]
                clip_durations = [snapped[0]] + [
                    max(0.5, snapped[i] - snapped[i - 1]) for i in range(1, len(snapped))
                ]

        motions = _pick_motions(n)
        tracker.start("VIDEO", f"{n} clips  Ken Burns · xfade")

        with tempfile.TemporaryDirectory(prefix="ffai_") as tmp:
            tmp_dir  = Path(tmp)
            clip_dir = tmp_dir / "clips"
            clip_dir.mkdir()
            clips_dict: dict[int, Path] = {}
            done_clips = [0]

            def _render_clip(idx: int) -> tuple[int, Path]:
                path = image_to_video(
                    images[idx], clip_durations[idx],
                    clip_dir / f"clip_{idx:03d}.mp4",
                    motion=motions[idx],
                )
                done_clips[0] += 1
                tracker.update("VIDEO", done_clips[0], n)
                return idx, path

            with ThreadPoolExecutor(max_workers=4) as ex:
                for idx, path in ex.map(_render_clip, range(n)):
                    clips_dict[idx] = path

            clips           = [clips_dict[i] for i in range(n)]
            raw_video       = tmp_dir / "raw.mp4"
            with_audio_path = tmp_dir / "with_audio.mp4"

            concat_with_transitions(clips, clip_durations, raw_video)
            merge_audio(raw_video, combined_audio, with_audio_path)
            tracker.complete("VIDEO", f"{n} clips  {total_dur:.1f}s")

            # ── 5. Captions ───────────────────────────────────────────────────
            tracker.start("CAPTIONS", f"faster-whisper  [{caption_style}]")
            ass_path      = tmp_dir / "captions.ass"
            subtitle_path = audio_to_ass(combined_audio, ass_path, style=caption_style)
            captioned     = tmp_dir / "captioned.mp4"
            burn_captions(with_audio_path, subtitle_path, captioned)
            tracker.complete("CAPTIONS", caption_style)

            # ── 6. Music ──────────────────────────────────────────────────────
            pre_encode = captioned
            if music_path is not None and music_path.is_file():
                tracker.start("MUSIC", f"{music_path.name}  sidechain")
                with_music = tmp_dir / "with_music.mp4"
                mix_music(captioned, music_path, with_music)
                tracker.complete("MUSIC", "auto-ducked")
                pre_encode = with_music

            # ── 7. Export ─────────────────────────────────────────────────────
            tracker.start("EXPORT", f"→ {output_path.name}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            final_encode(pre_encode, output_path)

            thumb_note = ""
            if thumbnail:
                thumb_path = output_path.with_suffix(".thumb.jpg")
                extract_thumbnail(output_path, thumb_path)
                thumb_note = "  +thumb"

            tracker.complete("EXPORT", f"→ {output_path.name}{thumb_note}")

    elapsed = time.time() - start_time
    img_src = (
        str(images_dir) if images_dir
        else ("AI (" + ", ".join(providers) + ")") if use_ai_images
        else "placeholder"
    )
    console.print(Panel(
        stats_table({
            "output":     str(output_path.resolve()),
            "duration":   f"{total_dur:.1f}s",
            "elapsed":    f"{elapsed:.0f}s",
            "model":      model,
            "voice":      voice,
            "images":     img_src + (f"  ({placeholder_count} placeholder)" if placeholder_count else ""),
            "style":      style or "default",
            "captions":   caption_style,
            "music":      music_path.name if music_path else "none",
            "job cache":  str(job_dir),
        }),
        title="[bold green]done[/]", border_style="green", box=box.ROUNDED,
    ))
    return output_path


def _pick_motions(n: int) -> list[str]:
    if n == 0:
        return []
    result = [random.choice(MOTION_STYLES)]
    for _ in range(n - 1):
        result.append(random.choice([s for s in MOTION_STYLES if s != result[-1]]))
    return result


def _energy_curve_durations(n: int, total_dur: float) -> list[float]:
    """TikTok energy curve: fast at hook and outro, slower in the body."""
    if n == 0:
        return []
    base = total_dur / n
    raw: list[float] = []
    for i in range(n):
        pos    = i / max(n - 1, 1)
        arc    = math.sin(math.pi * pos)
        factor = 0.65 + arc * 0.55
        jitter = random.uniform(0.90, 1.10)
        raw.append(max(1.2, base * factor * jitter))
    scale = total_dur / sum(raw)
    return [d * scale for d in raw]
