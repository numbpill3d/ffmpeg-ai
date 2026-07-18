"""Orchestrates the full Short generation pipeline."""
import asyncio
import hashlib
import json
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich import box

from .ui.display import console, warn
from .ui.widgets import PipelineTracker, stats_table
from .ai.openrouter import generate_script, FREE_MODELS
from .ai.images import generate_images, load_user_images, _ALL_PROVIDERS as _IMG_PROVIDERS
from .ai.tts import synthesize, DEFAULT_VOICE, rate_for_mode
from .video.composer import (
    image_to_video, concat_with_transitions, concat_plain, concat_audio,
    merge_audio, mix_music, burn_captions, encode_video, get_audio_duration,
    detect_beats, snap_to_beats, extract_thumbnail, add_hook_overlay, add_ambience,
    get_color_grade, MOTION_STYLES,
)
from .video.shorts import MODES
from .video.captions import audio_to_ass

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"
_RENDER_MODES = {"kenburns", "storyboard", "fast-preview"}


@dataclass(slots=True)
class RenderPlan:
    images: list[Path]
    clip_durations: list[float]
    transition_duration: float
    total_duration: float
    render_mode: str

    @property
    def clip_count(self) -> int:
        return len(self.images)


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"


def _find_font(font_override: Optional[str] = None) -> str:
    """Return path to a bold sans-serif font, or empty string to use ffmpeg's default.

    On Windows ffmpeg has no fontconfig, so a missing font makes drawtext fail
    hard. We therefore also probe common Windows font directories. A caller can
    force a specific font via ``font_override`` (e.g. from ``--font``).
    """
    if font_override:
        if Path(font_override).is_file():
            return str(font_override)
        warn(f"--font path not found: {font_override}; falling back to auto-detect")

    candidates = [
        # Linux
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/LiberationSans-Bold.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        # Windows
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\DejaVuSans-Bold.ttf",
    ]
    found = next((f for f in candidates if Path(f).exists()), "")
    if not found:
        # last resort: walk the Windows font dir if it exists
        win_fonts = Path(r"C:\Windows\Fonts")
        if win_fonts.is_dir():
            for cand in win_fonts.glob("*.ttf"):
                if "bold" in cand.name.lower() or cand.name.lower().startswith("arial"):
                    found = str(cand)
                    break
    return found


def _check_ffmpeg() -> None:
    """Verify ffmpeg and ffprobe are available on PATH."""
    for tool in ["ffmpeg", "ffprobe"]:
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"'{tool}' not found in PATH — install ffmpeg to use this tool"
            )


def _init_run_report(
    *,
    topic: str,
    output_path: Path,
    job_dir: Path,
    mode: str,
    duration: int,
    model: str,
    voice: str,
    style: Optional[str],
    caption_style: str,
    thumbnail: bool,
    music_path: Optional[Path],
    images_dir: Optional[Path],
    use_ai_images: bool,
    image_providers: list[str],
    fresh: bool,
    dry_run: bool,
    no_captions: bool,
    no_ambience: bool,
    no_hook: bool,
    brand_name: str,
    accent_color: str,
    render_mode: str = "kenburns",
) -> dict:
    if images_dir is not None:
        image_strategy = {"source": "user", "path": str(images_dir)}
    elif use_ai_images:
        image_strategy = {"source": "ai", "providers": image_providers}
    else:
        image_strategy = {"source": "placeholder", "providers": []}

    return {
        "topic": topic,
        "job_dir": str(job_dir),
        "output_path": str(output_path),
        "mode": mode,
        "duration_target_s": duration,
        "model_requested": model,
        "voice": voice,
        "style": style or "default",
        "caption_style": caption_style,
        "render_mode": render_mode,
        "thumbnail": {
            "enabled": thumbnail,
            "brand_name": brand_name,
            "accent_color": accent_color,
        },
        "music": {
            "enabled": music_path is not None,
            "path": str(music_path) if music_path is not None else None,
        },
        "image_strategy": image_strategy,
        "fresh": fresh,
        "dry_run": dry_run,
        "no_captions": no_captions,
        "no_ambience": no_ambience,
        "no_hook": no_hook,
        "status": "running",
    }


def _finalize_run_report(
    report: dict,
    job_dir: Path,
    *,
    status: str,
    elapsed_s: float,
    extra: Optional[dict] = None,
) -> Path:
    report["status"] = status
    report["elapsed_s"] = round(elapsed_s, 2)
    if extra:
        report.update(extra)
    path = job_dir / "run_report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _adapt_script(script: dict, *, topic: str) -> dict:
    def _fix_vp(obj: dict, fallback: str) -> None:
        vp = obj.get("visual_prompts")
        if not isinstance(vp, list) or len(vp) == 0:
            obj["visual_prompts"] = [vp] if isinstance(vp, str) else [fallback]

    if "hook" in script and isinstance(script["hook"], str):
        script["hook"] = {"text": script["hook"], "visual_prompts": [topic]}
    elif isinstance(script.get("hook"), dict):
        _fix_vp(script["hook"], topic)

    if "cta" in script and isinstance(script["cta"], str):
        script["cta"] = {"text": script["cta"], "visual_prompts": [topic]}
    elif isinstance(script.get("cta"), dict):
        _fix_vp(script["cta"], topic)

    for seg in script.get("segments", []):
        _fix_vp(seg, topic)
    return script


def _expand_timeline_for_pacing(
    *,
    prompts: list[str],
    part_mapping: list[tuple[float, int]],
    max_clip_duration: float,
) -> tuple[list[str], list[tuple[float, int]]]:
    """Repeat visual prompts so no narration part holds one visual too long.

    `part_mapping` describes the narration duration and original prompt count for
    each hook/segment/CTA part. When a part would leave a visual on screen longer
    than `max_clip_duration`, cycle that part's prompts until the part has enough
    visual beats. User-supplied image directories already cycle when asked for
    more images; AI providers receive repeated prompts with different frame
    indices/seeds.
    """
    if max_clip_duration <= 0:
        return prompts, part_mapping

    expanded: list[str] = []
    expanded_mapping: list[tuple[float, int]] = []
    cursor = 0

    for part_dur, prompt_count in part_mapping:
        part_prompts = prompts[cursor:cursor + prompt_count]
        cursor += prompt_count
        if prompt_count <= 0 or not part_prompts:
            expanded_mapping.append((part_dur, 0))
            continue

        target_count = max(prompt_count, math.ceil(part_dur / max_clip_duration))
        for i in range(target_count):
            expanded.append(part_prompts[i % len(part_prompts)])
        expanded_mapping.append((part_dur, target_count))

    return expanded, expanded_mapping


def _image_manifest_path(img_dir: Path) -> Path:
    return img_dir / "manifest.json"


def _image_cache_signature(
    *,
    prompts: list[str],
    width: int,
    height: int,
    use_ai_images: bool,
    providers: list[str],
) -> str:
    payload = {
        "prompts": prompts,
        "width": width,
        "height": height,
        "use_ai_images": use_ai_images,
        "providers": providers,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_image_manifest(img_dir: Path) -> dict | None:
    path = _image_manifest_path(img_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _read_image_run_report(img_dir: Path) -> dict | None:
    path = img_dir.parent / "run_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _cached_images_are_valid(
    img_dir: Path,
    expected_count: int,
    *,
    signature: str,
) -> tuple[bool, list[Path]]:
    """Reuse cached frames only when the cache says they are real generated images.

    The cache must match both the expected frame count and the current prompt
    signature. This prevents stale images from being reused after the script or
    render inputs change.
    """
    cached_frames = sorted(img_dir.glob("frame_*.jpg")) if img_dir.is_dir() else []
    if len(cached_frames) != expected_count:
        return False, cached_frames

    manifest = _read_image_manifest(img_dir)
    if manifest:
        try:
            placeholder_count = int(manifest.get("placeholder_count", 0))
        except (TypeError, ValueError):
            return False, cached_frames
        if placeholder_count != 0:
            return False, cached_frames
        if manifest.get("signature") != signature:
            return False, cached_frames
        return True, cached_frames

    run_report = _read_image_run_report(img_dir)
    if not run_report:
        return False, cached_frames

    try:
        placeholder_count = int(run_report.get("placeholder_count", 0))
    except (TypeError, ValueError):
        return False, cached_frames
    return placeholder_count == 0, cached_frames


def _default_render_mode(mode: str) -> str:
    return "storyboard" if mode == "landscape" else "kenburns"


def _validate_render_mode(render_mode: str | None, mode: str) -> str:
    selected = render_mode or _default_render_mode(mode)
    if selected not in _RENDER_MODES:
        raise ValueError(
            f"unknown render_mode {selected!r} — choose from: {', '.join(sorted(_RENDER_MODES))}"
        )
    return selected


def _raw_clip_durations(part_mapping: list[tuple[float, int]]) -> list[float]:
    durations: list[float] = []
    for part_dur, n_imgs in part_mapping:
        if n_imgs:
            durations.extend([part_dur / n_imgs] * n_imgs)
    return durations


def _plan_render(
    *,
    images: list[Path],
    part_mapping: list[tuple[float, int]],
    total_dur: float,
    max_duration: float,
    render_mode: str,
) -> RenderPlan:
    raw = _raw_clip_durations(part_mapping)
    n_clips = len(images)
    if n_clips == 0:
        raise RuntimeError("no images were generated — cannot produce video")
    if len(raw) != n_clips:
        raise RuntimeError(
            f"timeline/image mismatch: {len(raw)} durations for {n_clips} images"
        )

    trans_d = 0.0
    if render_mode == "kenburns" and n_clips > 1:
        trans_d = min(0.4, min(raw) * 0.25)
    total_overlap = (n_clips - 1) * trans_d
    extra_per_clip = total_overlap / n_clips if n_clips else 0
    clip_durations = [d + extra_per_clip for d in raw]

    planned_total = min(total_dur, max_duration)
    if total_dur > max_duration:
        current_v_sum = 0.0
        kept: list[float] = []
        for d in clip_durations:
            if current_v_sum + d > max_duration + total_overlap:
                break
            kept.append(d)
            current_v_sum += d
        clip_durations = kept
        images = images[:len(clip_durations)]

    return RenderPlan(
        images=list(images),
        clip_durations=clip_durations,
        transition_duration=trans_d,
        total_duration=planned_total,
        render_mode=render_mode,
    )


async def run_pipeline(
    topic: str,
    output_path: Path,
    mode: str = "shorts",
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
    no_ambience: bool = False,
    no_hook: bool = False,
    font_path: Optional[str] = None,
    brand_name: str = "",
    accent_color: str = "#c084ff",
    render_mode: Optional[str] = None,
) -> Path:
    """
    images_dir:       use images from this directory instead of AI generation.
    use_ai_images:    if False and no images_dir, uses PIL placeholder images.
    image_providers:  ordered list of AI providers: "pollinations", "huggingface".
    music_path:       optional background music file; auto-ducked under narration.
    script_path:      load script JSON from file instead of calling LLM.
    edit_script:      open generated script in $EDITOR before rendering.
    fresh:            ignore all cached job data and start from scratch.
    quiet:            suppress live TUI - one line per stage to stdout.
    thumbnail:        extract a thumbnail JPEG alongside the output file.
    style:            tone preset: educational, dramatic, listicle, documentary.
    caption_style:    karaoke, plain, or bold-center.
    no_captions:      skip transcription and caption burn entirely.
    no_ambience:      skip the ambience audio layer.
    no_hook:          skip the hook text overlay entirely (Windows-safe).
    font_path:        explicit .ttf path for overlays/captions (else auto-detected).
    """
    _check_ffmpeg()
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r} — choose from: {', '.join(MODES)}")
    render_mode = _validate_render_mode(render_mode, mode)
    spec = MODES[mode]
    start_time = time.time()
    providers = image_providers or _IMG_PROVIDERS

    job_dir = _JOB_CACHE / _slug(topic)
    if fresh:
        shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    report = _init_run_report(
        topic=topic,
        output_path=output_path,
        job_dir=job_dir,
        mode=mode,
        duration=duration,
        model=model,
        voice=voice,
        style=style,
        caption_style=caption_style,
        render_mode=render_mode,
        thumbnail=thumbnail,
        music_path=music_path,
        images_dir=images_dir,
        use_ai_images=use_ai_images,
        image_providers=providers,
        fresh=fresh,
        dry_run=dry_run,
        no_captions=no_captions,
        no_ambience=no_ambience,
        no_hook=no_hook,
        brand_name=brand_name,
        accent_color=accent_color,
    )
    report["cache_hits"] = {"script": False, "tts": False, "images": False}
    report["artifacts"] = {}
    report["script"] = {"source": None, "title": None, "segment_count": 0}
    report["captions"] = {"enabled": not no_captions, "status": "pending"}
    report["hook_overlay"] = {"enabled": (not no_hook) and (mode == "shorts"), "status": "pending"}
    report["thumbnail_result"] = {"enabled": thumbnail, "status": "pending"}
    report["placeholder_count"] = 0
    report["failed_stage"] = None
    current_stage: Optional[str] = None

    stages = ["SCRIPT", "TTS", "IMAGES", "VIDEO", "CAPTIONS", "AMBIENCE"]
    if music_path and music_path.is_file():
        stages.append("MUSIC")
    stages.append("EXPORT")

    try:
        with PipelineTracker(stages, quiet=quiet) as tracker:
            current_stage = "SCRIPT"
            script_cache = job_dir / "script.json"

            script = None
            if script_path is not None:
                try:
                    script = json.loads(Path(script_path).read_text())
                except (json.JSONDecodeError, OSError) as e:
                    raise RuntimeError(f"could not load script from {script_path}: {e}") from e
                report["script"]["source"] = "file"
                report["artifacts"]["script_path"] = str(Path(script_path))
                tracker.complete("SCRIPT", "loaded from file", cached=True)
            elif not fresh and script_cache.exists():
                try:
                    script = json.loads(script_cache.read_text())
                    report["cache_hits"]["script"] = True
                    report["script"]["source"] = "cache"
                    report["artifacts"]["script_path"] = str(script_cache)
                    tracker.complete("SCRIPT", "loaded from cache", cached=True)
                except (json.JSONDecodeError, OSError):
                    script_cache.unlink(missing_ok=True)

            if script is None:
                model_short = model.split("/")[-1]
                tracker.start("SCRIPT", f"model: {model_short}")
                script = await generate_script(
                    topic,
                    duration=duration,
                    model=model,
                    style=style,
                    mode=mode,
                )
                script_cache.write_text(json.dumps(script, indent=2))
                report["script"]["source"] = "generated"
                report["artifacts"]["script_path"] = str(script_cache)
                tracker.complete("SCRIPT", "generated new script")

            script = _adapt_script(script, topic=topic)
            hook = script["hook"]
            segments = script["segments"]
            cta = script["cta"]
            viral = script.get("viral_package", {})
            report["script"]["title"] = script.get("title", "")
            report["script"]["segment_count"] = len(segments)

            metadata_path = job_dir / "metadata.json"
            metadata_path.write_text(json.dumps(viral, indent=2))
            report["artifacts"]["metadata_path"] = str(metadata_path)

            tracker.print(Panel(
                stats_table({
                    "title": script.get("title", ""),
                    "hook": hook["text"][:80],
                    "segments": str(len(segments)),
                }),
                title="[cyan]script[/]",
                border_style="bright_black",
                box=box.ROUNDED,
            ))

            if edit_script:
                edit_file = job_dir / "script_edit.json"
                edit_file.write_text(json.dumps(script, indent=2))
                if tracker._live:
                    tracker._live.stop()
                editor = os.environ.get("EDITOR", "nano")
                try:
                    subprocess.run([*shlex.split(editor), str(edit_file)])
                except FileNotFoundError:
                    raise RuntimeError(
                        f"editor not found: {editor!r} — set $EDITOR to an installed editor"
                    )
                script = _adapt_script(json.loads(edit_file.read_text()), topic=topic)
                script_cache.write_text(json.dumps(script, indent=2))
                hook = script["hook"]
                segments = script["segments"]
                cta = script["cta"]
                if tracker._live:
                    tracker._live.start()
                report["script"]["source"] = "edited"
                report["script"]["title"] = script.get("title", "")
                report["script"]["segment_count"] = len(segments)

            if dry_run:
                for stage_name in [s for s in stages if s != "SCRIPT"]:
                    tracker.complete(stage_name, "skipped (dry run)")
                report["captions"] = {
                    "enabled": not no_captions,
                    "status": "skipped (dry run)",
                }
                report["thumbnail_result"] = {
                    "enabled": thumbnail,
                    "status": "skipped (dry run)",
                }
                _finalize_run_report(
                    report,
                    job_dir,
                    status="dry_run",
                    elapsed_s=time.time() - start_time,
                    extra={
                        "artifacts": report["artifacts"],
                        "script": report["script"],
                        "captions": report["captions"],
                        "thumbnail_result": report["thumbnail_result"],
                    },
                )
                return output_path

            current_stage = "TTS"
            tts_dir = job_dir / "tts"
            img_dir = job_dir / "images"
            combined_audio = job_dir / "narration.mp3"

            tts_dir.mkdir(parents=True, exist_ok=True)
            img_dir.mkdir(parents=True, exist_ok=True)
            report["artifacts"]["tts_dir"] = str(tts_dir)
            report["artifacts"]["images_dir"] = str(img_dir)
            report["artifacts"]["narration_path"] = str(combined_audio)

            tts_rate = rate_for_mode(mode)
            tracker.start("TTS", f"voice: {voice.split('-')[-1]}")

            async def _do_tts_and_sync() -> tuple[Path, float, list[str], list[tuple[float, int]]]:
                hook_audio = tts_dir / "hook.mp3"
                cta_audio = tts_dir / "cta.mp3"
                seg_paths = [tts_dir / f"seg_{i:03d}.mp3" for i in range(len(segments))]

                all_texts = [hook["text"], cta["text"]] + [s["text"] for s in segments]
                tts_hash = hashlib.sha256((voice + tts_rate + "".join(all_texts)).encode()).hexdigest()[:16]
                hash_file = tts_dir / "hash.txt"
                all_segs = [hook_audio] + seg_paths + [cta_audio]
                tts_cached = (
                    not fresh
                    and hash_file.exists()
                    and hash_file.read_text().strip() == tts_hash
                    and all(p.exists() for p in all_segs)
                )

                if not tts_cached:
                    await asyncio.gather(
                        synthesize(hook["text"], hook_audio, voice=voice, rate=tts_rate),
                        synthesize(cta["text"], cta_audio, voice=voice, rate=tts_rate),
                        *[
                            synthesize(seg["text"], seg_paths[i], voice=voice, rate=tts_rate)
                            for i, seg in enumerate(segments)
                        ],
                    )
                    hash_file.write_text(tts_hash)
                report["cache_hits"]["tts"] = tts_cached

                all_a = [hook_audio] + seg_paths + [cta_audio]
                await asyncio.to_thread(concat_audio, all_a, combined_audio)
                durs = await asyncio.gather(*[asyncio.to_thread(get_audio_duration, a) for a in all_a])
                h_dur, *mid, c_dur = durs
                seg_durs = mid

                timeline_prompts: list[str] = []
                part_mapping: list[tuple[float, int]] = []

                timeline_prompts.extend(hook["visual_prompts"])
                part_mapping.append((h_dur, len(hook["visual_prompts"])))
                for i, seg in enumerate(segments):
                    timeline_prompts.extend(seg["visual_prompts"])
                    part_mapping.append((seg_durs[i], len(seg["visual_prompts"])))
                timeline_prompts.extend(cta["visual_prompts"])
                part_mapping.append((c_dur, len(cta["visual_prompts"])))

                total_dur = sum(d for d, _ in part_mapping)
                cache_note = "  (cached)" if tts_cached else ""
                tracker.complete("TTS", f"{total_dur:.1f}s{cache_note}")
                return combined_audio, total_dur, timeline_prompts, part_mapping

            combined_audio, total_dur, image_prompts, part_mapping = await _do_tts_and_sync()
            max_clip_duration = spec.max_visual_hold
            image_prompts, part_mapping = _expand_timeline_for_pacing(
                prompts=image_prompts,
                part_mapping=part_mapping,
                max_clip_duration=max_clip_duration,
            )
            report["duration_actual_s"] = round(total_dur, 2)
            report["max_clip_duration_s"] = max_clip_duration
            report["image_prompt_count"] = len(image_prompts)
            image_cache_sig = _image_cache_signature(
                prompts=image_prompts,
                width=spec.width,
                height=spec.height,
                use_ai_images=use_ai_images,
                providers=providers,
            )

            current_stage = "IMAGES"
            n_total_images = len(image_prompts)
            tracker.start("IMAGES", f"{n_total_images} frames (synced)")
            tracker.set_image_count(n_total_images)

            async def _do_images() -> tuple[list[Path], int]:
                provider_attempts: list[dict] = []
                report["image_provider_attempts"] = provider_attempts

                def _record_attempt(frame: int, provider: str, ok: bool) -> None:
                    provider_attempts.append({"frame": frame, "provider": provider, "ok": ok})

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

                cache_ok, cached_frames = _cached_images_are_valid(
                    img_dir,
                    n_total_images,
                    signature=image_cache_sig,
                )
                if not fresh and cache_ok:
                    report["cache_hits"]["images"] = True
                    imgs = cached_frames
                    for i in range(len(imgs)):
                        tracker.image_done(i, False)
                    tracker.complete("IMAGES", f"{n_total_images} cached", cached=True)
                    return imgs, 0

                if not use_ai_images:
                    from .ai.images import _make_placeholder

                    imgs = [
                        _make_placeholder(p, img_dir / f"frame_{i:03d}.jpg", spec.width, spec.height)
                        for i, p in enumerate(image_prompts)
                    ]
                    for i in range(len(imgs)):
                        tracker.image_done(i, True)
                    tracker.complete("IMAGES", f"{n_total_images} placeholders")
                    manifest_path = _image_manifest_path(img_dir)
                    manifest_path.write_text(
                        json.dumps(
                            {
                                "placeholder_count": n_total_images,
                                "signature": image_cache_sig,
                                "provider_attempts": [],
                                "use_ai_images": use_ai_images,
                                "providers": providers,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    report["artifacts"]["image_manifest_path"] = str(manifest_path)
                    return imgs, n_total_images

                img_concurrency = 2 if max(spec.width, spec.height) >= 1280 else 4
                imgs, pc = await generate_images(
                    image_prompts,
                    img_dir,
                    providers=providers,
                    max_concurrent=img_concurrency,
                    on_image_done=lambda i, is_pl: tracker.image_done(i, is_pl),
                    on_attempt=_record_attempt,
                    width=spec.width,
                    height=spec.height,
                )
                detail = f"{len(imgs)} images"
                if pc:
                    detail += f"  ({pc} placeholder)"
                tracker.complete("IMAGES", detail)
                manifest_path = _image_manifest_path(img_dir)
                manifest_path.write_text(
                    json.dumps(
                        {
                            "placeholder_count": pc,
                            "signature": image_cache_sig,
                            "provider_attempts": report.get("image_provider_attempts", []),
                            "use_ai_images": use_ai_images,
                            "providers": providers,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                report["artifacts"]["image_manifest_path"] = str(manifest_path)
                return imgs, pc

            images, placeholder_count = await _do_images()
            report["placeholder_count"] = placeholder_count

            current_stage = "VIDEO"
            plan = _plan_render(
                images=images,
                part_mapping=part_mapping,
                total_dur=total_dur,
                max_duration=spec.max_duration,
                render_mode=render_mode,
            )
            images = plan.images
            clip_durations = plan.clip_durations
            total_dur = plan.total_duration
            n_clips = plan.clip_count
            trans_d = plan.transition_duration

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
                    plan.clip_durations = clip_durations

            motions = _pick_motions(n_clips)
            if render_mode in {"storyboard", "fast-preview"}:
                motions = ["subtle_zoom"] * n_clips
            color_grade = get_color_grade(style)
            report["video"] = {
                "clip_count": n_clips,
                "render_mode": render_mode,
                "transition_duration_s": round(trans_d, 3),
                "color_grade": color_grade,
            }
            tracker.start("VIDEO", f"{n_clips} clips  {render_mode}")

            with tempfile.TemporaryDirectory(prefix="ffai_") as tmp:
                tmp_dir = Path(tmp)
                clip_dir = tmp_dir / "clips"
                clip_dir.mkdir()
                clips_dict: dict[int, Path] = {}
                done_clips = [0]
                clip_lock = threading.Lock()

                def _render_clip(idx: int) -> tuple[int, Path]:
                    path = image_to_video(
                        images[idx],
                        clip_durations[idx],
                        clip_dir / f"clip_{idx:03d}.mp4",
                        spec=spec,
                        motion=motions[idx],
                        color_grade=color_grade,
                    )
                    with clip_lock:
                        done_clips[0] += 1
                        tracker.update("VIDEO", done_clips[0], n_clips)
                    return idx, path

                with ThreadPoolExecutor(max_workers=4) as ex:
                    for idx, clip_path in ex.map(_render_clip, range(n_clips)):
                        clips_dict[idx] = clip_path

                clips = [clips_dict[i] for i in range(n_clips)]
                raw_video = tmp_dir / "raw.mp4"
                with_audio_path = tmp_dir / "with_audio.mp4"

                if render_mode == "kenburns":
                    concat_with_transitions(clips, clip_durations, raw_video, transition_duration=trans_d)
                else:
                    concat_plain(clips, raw_video)
                merge_audio(raw_video, combined_audio, with_audio_path)

                if mode == "shorts" and not no_hook:
                    captioned_hook = tmp_dir / "hooked.mp4"
                    try:
                        add_hook_overlay(
                            with_audio_path,
                            hook["text"],
                            _find_font(font_override=font_path),
                            captioned_hook,
                        )
                        report["hook_overlay"] = {
                            "enabled": True,
                            "status": "burned",
                            "font": _find_font(font_override=font_path) or "ffmpeg-default",
                        }
                    except Exception as hook_err:
                        # drawtext can fail on platforms without fontconfig
                        # (e.g. Windows). Don't abort the whole pipeline — keep
                        # the clean video and continue to captions/export.
                        report["hook_overlay"] = {
                            "enabled": True,
                            "status": "failed",
                            "error": str(hook_err),
                        }
                        warn(f"hook overlay skipped — {hook_err}")
                        captioned_hook = with_audio_path
                else:
                    captioned_hook = with_audio_path
                tracker.complete("VIDEO", f"{n_clips} clips  {total_dur:.1f}s")

                current_stage = "CAPTIONS"
                pre_caption = captioned_hook
                if no_captions:
                    report["captions"] = {"enabled": False, "status": "skipped"}
                    tracker.complete("CAPTIONS", "skipped (--no-captions)")
                    post_caption = pre_caption
                else:
                    tracker.start("CAPTIONS", f"faster-whisper  [{caption_style}]")
                    try:
                        ass_path = tmp_dir / "captions.ass"
                        subtitle_path = await asyncio.to_thread(
                            audio_to_ass,
                            combined_audio,
                            ass_path,
                            style=caption_style,
                            mode=mode,
                        )
                        captioned = tmp_dir / "captioned.mp4"
                        await asyncio.to_thread(burn_captions, pre_caption, subtitle_path, captioned)
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        sub_out = output_path.with_suffix(subtitle_path.suffix)
                        shutil.copy2(subtitle_path, sub_out)
                        report["captions"] = {
                            "enabled": True,
                            "status": "burned",
                            "subtitle_path": str(sub_out),
                            "format": subtitle_path.suffix.lstrip("."),
                        }
                        tracker.complete("CAPTIONS", caption_style)
                        post_caption = captioned
                    except Exception as cap_err:
                        report["captions"] = {
                            "enabled": True,
                            "status": "failed",
                            "error": str(cap_err),
                        }
                        tracker.fail("CAPTIONS", f"skipped — {cap_err}")
                        post_caption = pre_caption

                current_stage = "AMBIENCE"
                if no_ambience:
                    tracker.complete("AMBIENCE", "skipped (--no-ambience)")
                    pre_encode = post_caption
                else:
                    tracker.start("AMBIENCE", "layered soundscapes")
                    final_audio_path = tmp_dir / "with_ambience.mp4"
                    add_ambience(post_caption, final_audio_path)
                    tracker.complete("AMBIENCE", "tech-hum layer added")
                    pre_encode = final_audio_path

                current_stage = "MUSIC"
                if music_path is not None and music_path.is_file():
                    tracker.start("MUSIC", f"{music_path.name}  sidechain")
                    with_music = tmp_dir / "with_music.mp4"
                    mix_music(pre_encode, music_path, with_music)
                    tracker.complete("MUSIC", "auto-ducked")
                    pre_encode = with_music

                current_stage = "EXPORT"
                tracker.start("EXPORT", f"→ {output_path.name}")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                encode_video(pre_encode, output_path, spec)
                report["artifacts"]["video_path"] = str(output_path.resolve())

                thumb_note = ""
                if thumbnail:
                    thumb_path = output_path.with_suffix(".thumb.jpg")
                    try:
                        from .video.thumbnail import make_thumbnail_from_job

                        script_title = script.get("title", topic)
                        designed = make_thumbnail_from_job(
                            job_dir=job_dir,
                            title=script_title,
                            output_path=thumb_path,
                            mode=mode,
                            brand_name=brand_name,
                            accent_color=accent_color,
                        )
                        if designed is not None:
                            report["thumbnail_result"] = {
                                "enabled": True,
                                "status": "designed",
                                "path": str(thumb_path),
                            }
                            thumb_note = "  +thumb(designed)"
                        else:
                            extract_thumbnail(output_path, thumb_path)
                            report["thumbnail_result"] = {
                                "enabled": True,
                                "status": "extracted",
                                "path": str(thumb_path),
                            }
                            thumb_note = "  +thumb"
                    except Exception as thumb_err:
                        extract_thumbnail(output_path, thumb_path)
                        report["thumbnail_result"] = {
                            "enabled": True,
                            "status": "extracted",
                            "path": str(thumb_path),
                            "fallback_error": str(thumb_err),
                        }
                        thumb_note = "  +thumb"
                else:
                    report["thumbnail_result"] = {"enabled": False, "status": "skipped"}

                tracker.complete("EXPORT", f"→ {output_path.name}{thumb_note}")

        elapsed = time.time() - start_time
        report_path = _finalize_run_report(
            report,
            job_dir,
            status="succeeded",
            elapsed_s=elapsed,
            extra={
                "artifacts": report["artifacts"],
                "script": report["script"],
                "captions": report["captions"],
                "thumbnail_result": report["thumbnail_result"],
                "placeholder_count": report["placeholder_count"],
            },
        )
        img_src = (
            str(images_dir)
            if images_dir
            else ("AI (" + ", ".join(providers) + ")") if use_ai_images
            else "placeholder"
        )
        placeholder_note = f"  ({placeholder_count} placeholder)" if placeholder_count else ""
        console.print(Panel(
            stats_table({
                "output": str(output_path.resolve()),
                "duration": f"{total_dur:.1f}s",
                "elapsed": f"{elapsed:.0f}s",
                "model": model,
                "voice": voice,
                "images": img_src + placeholder_note,
                "style": style or "default",
                "captions": report["captions"].get("status", caption_style),
                "music": music_path.name if music_path else "none",
                "job cache": str(job_dir),
                "run report": str(report_path),
            }),
            title="[bold green]done[/]",
            border_style="green",
            box=box.ROUNDED,
        ))
        return output_path
    except Exception as err:
        report["failed_stage"] = current_stage
        _finalize_run_report(
            report,
            job_dir,
            status="failed",
            elapsed_s=time.time() - start_time,
            extra={
                "error": str(err),
                "error_type": type(err).__name__,
                "failed_stage": current_stage,
                "artifacts": report["artifacts"],
                "script": report["script"],
                "captions": report["captions"],
                "thumbnail_result": report["thumbnail_result"],
                "placeholder_count": report["placeholder_count"],
            },
        )
        raise


def _pick_motions(n: int) -> list[str]:
    if n == 0:
        return []
    result = [random.choice(MOTION_STYLES)]
    for _ in range(n - 1):
        result.append(random.choice([s for s in MOTION_STYLES if s != result[-1]]))
    return result
