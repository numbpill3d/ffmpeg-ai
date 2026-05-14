"""Orchestrates the full Short generation pipeline."""
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich import box

from .ui.display import console
from .ui.widgets import PipelineTracker, stats_table
from .ai.openrouter import generate_script, FREE_MODELS
from .ai.images import generate_images, load_user_images
from .ai.tts import synthesize_segments, synthesize, DEFAULT_VOICE
from .video.composer import (
    image_to_video, concat_with_transitions, concat_audio,
    merge_audio, mix_music, burn_captions, final_encode, get_audio_duration,
    detect_beats, snap_to_beats, extract_thumbnail, add_hook_overlay, add_ambience,
    MOTION_STYLES,
)
from .video.captions import audio_to_ass

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"


def _find_font() -> str:
    """Return path to a bold sans-serif font, or empty string to use ffmpeg's default."""
    candidates = [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/DejaVuSans-Bold.ttf",
    ]
    return next((f for f in candidates if Path(f).exists()), "")


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
    no_captions: bool = False,
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
    no_captions:      skip transcription and caption burn entirely.
    """
    start_time = time.time()

    job_dir = _JOB_CACHE / _slug(topic)
    if fresh:
        shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    stages = ["SCRIPT", "TTS", "IMAGES", "VIDEO", "CAPTIONS", "AMBIENCE"]
    if music_path and music_path.is_file():
        stages.append("MUSIC")
    stages.append("EXPORT")

    with PipelineTracker(stages, quiet=quiet) as tracker:

        # ── 1. Script ────────────────────────────────────────────────────────
        script_cache = job_dir / "script.json"

        if script_path is not None:
            script = json.loads(Path(script_path).read_text())
            tracker.complete("SCRIPT", "loaded from file", cached=True)
        elif not fresh and script_cache.exists():
            script = json.loads(script_cache.read_text())
            tracker.complete("SCRIPT", "loaded from cache", cached=True)
        else:
            model_short = model.split("/")[-1]
            tracker.start("SCRIPT", f"model: {model_short}")
            script = await generate_script(
                topic, duration=duration, model=model,
                style=style,
            )
            script_cache.write_text(json.dumps(script, indent=2))
            tracker.complete("SCRIPT", "generated new script")

        def _adapt_script(s: dict) -> dict:
            def _fix_vp(obj: dict, fallback: str) -> None:
                vp = obj.get("visual_prompts")
                if not isinstance(vp, list):
                    obj["visual_prompts"] = [vp] if isinstance(vp, str) else [fallback]

            if "hook" in s and isinstance(s["hook"], str):
                s["hook"] = {"text": s["hook"], "visual_prompts": [topic]}
            elif isinstance(s.get("hook"), dict):
                _fix_vp(s["hook"], topic)

            if "cta" in s and isinstance(s["cta"], str):
                s["cta"] = {"text": s["cta"], "visual_prompts": [topic]}
            elif isinstance(s.get("cta"), dict):
                _fix_vp(s["cta"], topic)

            for seg in s.get("segments", []):
                _fix_vp(seg, topic)
            return s

        script = _adapt_script(script)
        hook = script["hook"]
        segments = script["segments"]
        cta = script["cta"]
        viral = script.get("viral_package", {})

        # Save metadata package
        (job_dir / "metadata.json").write_text(json.dumps(viral, indent=2))

        tracker.print(Panel(
            stats_table({
                "title":    script.get("title", ""),
                "hook":     hook["text"][:80],
                "segments": str(len(segments)),
            }),
            title="[cyan]script[/]", border_style="bright_black", box=box.ROUNDED,
        ))

        if edit_script:
            edit_file = job_dir / "script_edit.json"
            edit_file.write_text(json.dumps(script, indent=2))
            if tracker._live:
                tracker._live.stop()
            editor = os.environ.get("EDITOR", "nano")
            try:
                subprocess.run([editor, str(edit_file)])
            except FileNotFoundError:
                raise RuntimeError(
                    f"editor not found: {editor!r} — set $EDITOR to an installed editor"
                )
            script = _adapt_script(json.loads(edit_file.read_text()))
            script_cache.write_text(json.dumps(script, indent=2))
            # Re-bind locals so TTS uses the edited script
            hook = script["hook"]
            segments = script["segments"]
            cta = script["cta"]
            if tracker._live:
                tracker._live.start()

        if dry_run:
            skip = [s for s in stages if s != "SCRIPT"]
            for s in skip:
                tracker.complete(s, "skipped (dry run)")
            return output_path

        providers = image_providers or ["bfl", "fal", "prodia", "pollinations", "huggingface"]

        # ── 2+3. TTS + Images (Semantic Sync) ────────────────────────────────
        tts_dir = job_dir / "tts"
        img_dir = job_dir / "images"
        combined_audio = job_dir / "narration.mp3"

        tts_dir.mkdir(parents=True, exist_ok=True)
        img_dir.mkdir(parents=True, exist_ok=True)

        tracker.start("TTS", f"voice: {voice.split('-')[-1]}")

        async def _do_tts_and_sync() -> tuple[Path, float, list[str], list[tuple[float, int]]]:
            # 1. Synthesize all parts
            hook_audio = tts_dir / "hook.mp3"
            await synthesize(hook["text"], hook_audio, voice=voice)

            seg_audios = await synthesize_segments(segments, tts_dir, voice=voice)

            cta_audio = tts_dir / "cta.mp3"
            await synthesize(cta["text"], cta_audio, voice=voice)

            all_a = [hook_audio] + list(seg_audios) + [cta_audio]
            await asyncio.to_thread(concat_audio, all_a, combined_audio)

            # 2. Map parts to visual prompts and measure durations
            timeline_prompts = []
            part_mapping = []  # list of (duration, n_images)

            h_dur = await asyncio.to_thread(get_audio_duration, hook_audio)
            timeline_prompts.extend(hook["visual_prompts"])
            part_mapping.append((h_dur, len(hook["visual_prompts"])))

            for i, seg in enumerate(segments):
                s_dur = await asyncio.to_thread(get_audio_duration, seg_audios[i])
                timeline_prompts.extend(seg["visual_prompts"])
                part_mapping.append((s_dur, len(seg["visual_prompts"])))

            c_dur = await asyncio.to_thread(get_audio_duration, cta_audio)
            timeline_prompts.extend(cta["visual_prompts"])
            part_mapping.append((c_dur, len(cta["visual_prompts"])))

            total_dur = sum(d for d, _ in part_mapping)
            tracker.complete("TTS", f"{total_dur:.1f}s")
            return combined_audio, total_dur, timeline_prompts, part_mapping

        # We must do TTS first to get durations, then Images
        combined_audio, total_dur, image_prompts, part_mapping = await _do_tts_and_sync()

        n_total_images = len(image_prompts)
        tracker.start("IMAGES", f"{n_total_images} frames (synced)")
        tracker.set_image_count(n_total_images)

        async def _do_images() -> tuple[list[Path], int]:
            if images_dir is not None:
                src = load_user_images(images_dir, n_total_images)
                imgs: list[Path] = []
                for i, s in enumerate(src):
                    dst = img_dir / f"frame_{i:03d}{s.suffix.lower()}"
                    shutil.copy2(s, dst)
                    imgs.append(dst)
                    tracker.image_done(i, False)
                tracker.complete("IMAGES", f"{len(imgs)} user images")
                return imgs, 0

            # Always regenerate if counts don't match exactly
            cached_frames = sorted(img_dir.glob("frame_*.jpg")) if img_dir.is_dir() else []
            if not fresh and len(cached_frames) == n_total_images:
                imgs = cached_frames
                for i in range(len(imgs)):
                    tracker.image_done(i, False)
                tracker.complete("IMAGES", f"{n_total_images} cached", cached=True)
                return imgs, 0

            if not use_ai_images:
                from .ai.images import _make_placeholder
                imgs = [
                    _make_placeholder(p, img_dir / f"frame_{i:03d}.jpg")
                    for i, p in enumerate(image_prompts)
                ]
                for i in range(len(imgs)):
                    tracker.image_done(i, True)
                tracker.complete("IMAGES", f"{n_total_images} placeholders")
                return imgs, n_total_images

            imgs, pc = await generate_images(
                image_prompts, img_dir, providers=providers,
                max_concurrent=4,
                on_image_done=lambda i, is_pl: tracker.image_done(i, is_pl),
            )
            detail = f"{len(imgs)} images"
            if pc:
                detail += f"  ({pc} placeholder)"
            tracker.complete("IMAGES", detail)
            return imgs, pc

        images, placeholder_count = await _do_images()

        # ── 4. Video clips ────────────────────────────────────────────────────
        # 1. Create raw durations from audio parts
        raw_clip_durations = []
        for p_dur, n_imgs in part_mapping:
            if n_imgs == 0:
                continue
            avg = p_dur / n_imgs
            raw_clip_durations.extend([avg] * n_imgs)

        # 2. Compensate for xfade transition overlaps
        # sum(clip_durations) must be total_dur + (n_clips - 1) * trans_d
        n_clips = len(images)
        if n_clips == 0:
            raise RuntimeError("no images were generated — cannot produce video")
        trans_d = min(0.4, min(raw_clip_durations) * 0.25) if n_clips > 1 else 0
        total_overlap = (n_clips - 1) * trans_d
        extra_per_clip = total_overlap / n_clips
        clip_durations = [d + extra_per_clip for d in raw_clip_durations]

        # 3. Limit to 58s
        if total_dur > 58.0:
            total_dur = 58.0
            current_v_sum = 0.0
            new_durations = []
            for d in clip_durations:
                if current_v_sum + d > 58.0 + total_overlap:
                    break
                new_durations.append(d)
                current_v_sum += d
            clip_durations = new_durations
            images = images[:len(clip_durations)]
            n_clips = len(images)

        # 4. Music Beat Snapping
        if music_path is not None and music_path.is_file():
            beats = detect_beats(music_path)
            if beats:
                cut_t: list[float] = []
                t = 0.0
                for d in clip_durations[:-1]:
                    t += d
                    cut_t.append(t)
                snapped = snap_to_beats(cut_t, beats) + [sum(clip_durations)]
                clip_durations = [snapped[0]] + [
                    max(0.5, snapped[i] - snapped[i - 1]) for i in range(1, len(snapped))
                ]

        motions = _pick_motions(n_clips)
        tracker.start("VIDEO", f"{n_clips} clips  Ken Burns · xfade")

        with tempfile.TemporaryDirectory(prefix="ffai_") as tmp:
            tmp_dir = Path(tmp)
            clip_dir = tmp_dir / "clips"
            clip_dir.mkdir()
            clips_dict: dict[int, Path] = {}
            done_clips = [0]
            _clip_lock = threading.Lock()

            def _render_clip(idx: int) -> tuple[int, Path]:
                path = image_to_video(
                    images[idx], clip_durations[idx],
                    clip_dir / f"clip_{idx:03d}.mp4",
                    motion=motions[idx],
                )
                with _clip_lock:
                    done_clips[0] += 1
                    tracker.update("VIDEO", done_clips[0], n_clips)
                return idx, path

            with ThreadPoolExecutor(max_workers=4) as ex:
                for idx, path in ex.map(_render_clip, range(n_clips)):
                    clips_dict[idx] = path

            clips = [clips_dict[i] for i in range(n_clips)]
            raw_video = tmp_dir / "raw.mp4"
            with_audio_path = tmp_dir / "with_audio.mp4"

            concat_with_transitions(clips, clip_durations, raw_video, transition_duration=trans_d)
            merge_audio(raw_video, combined_audio, with_audio_path)

            # Apply hook overlay
            captioned_hook = tmp_dir / "hooked.mp4"
            add_hook_overlay(with_audio_path, hook["text"], _find_font(), captioned_hook)
            tracker.complete("VIDEO", f"{n_clips} clips  {total_dur:.1f}s")

            # ── 5. Captions ───────────────────────────────────────────────────
            pre_caption = captioned_hook
            if no_captions:
                tracker.complete("CAPTIONS", "skipped (--no-captions)")
                post_caption = pre_caption
            else:
                tracker.start("CAPTIONS", f"faster-whisper  [{caption_style}]")
                try:
                    ass_path = tmp_dir / "captions.ass"
                    subtitle_path = await asyncio.to_thread(
                        audio_to_ass, combined_audio, ass_path, style=caption_style,
                    )
                    captioned = tmp_dir / "captioned.mp4"
                    await asyncio.to_thread(burn_captions, pre_caption, subtitle_path, captioned)
                    tracker.complete("CAPTIONS", caption_style)
                    post_caption = captioned
                except Exception as cap_err:
                    tracker.fail("CAPTIONS", f"skipped — {cap_err}")
                    post_caption = pre_caption

            # ── 5a. Ambience ──────────────────────────────────────────────────
            tracker.start("AMBIENCE", "layered soundscapes")
            final_audio_path = tmp_dir / "with_ambience.mp4"
            add_ambience(post_caption, final_audio_path)
            tracker.complete("AMBIENCE", "tech-hum layer added")
            pre_encode = final_audio_path

            # ── 6. Music ──────────────────────────────────────────────────────
            if music_path is not None and music_path.is_file():
                tracker.start("MUSIC", f"{music_path.name}  sidechain")
                with_music = tmp_dir / "with_music.mp4"
                mix_music(pre_encode, music_path, with_music)
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
    placeholder_note = f"  ({placeholder_count} placeholder)" if placeholder_count else ""
    console.print(Panel(
        stats_table({
            "output":     str(output_path.resolve()),
            "duration":   f"{total_dur:.1f}s",
            "elapsed":    f"{elapsed:.0f}s",
            "model":      model,
            "voice":      voice,
            "images":     img_src + placeholder_note,
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
