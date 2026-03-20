"""All ffmpeg subprocess calls live here."""
import random
import shutil
import subprocess
from pathlib import Path
from .shorts import WIDTH, HEIGHT, FPS, SHORTS_VIDEO_ARGS


def _run(cmd: list[str], label: str = "ffmpeg"):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{result.stderr}")
    return result


def get_audio_duration(audio_path: Path) -> float:
    """Return duration of an audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


# ── Ken Burns motion styles ───────────────────────────────────────────────────

MOTION_STYLES = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]


def _kenburns_filter(motion: str, duration: float) -> str:
    """Return a zoompan filter string for the given motion style."""
    d = int(duration * FPS)
    if motion == "zoom_in":
        return (
            f"zoompan=z='min(zoom+0.0008,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if motion == "zoom_out":
        return (
            f"zoompan=z='if(eq(on,1),1.2,max(zoom-0.0008,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if motion == "pan_right":
        return (
            f"zoompan=z=1.2:x='iw*(1-1/zoom)*on/{d}':y='ih*(1-1/zoom)/2'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if motion == "pan_left":
        return (
            f"zoompan=z=1.2:x='iw*(1-1/zoom)*(1-on/{d})':y='ih*(1-1/zoom)/2'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if motion == "pan_up":
        return (
            f"zoompan=z=1.2:x='iw*(1-1/zoom)/2':y='ih*(1-1/zoom)*(1-on/{d})'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if motion == "pan_down":
        return (
            f"zoompan=z=1.2:x='iw*(1-1/zoom)/2':y='ih*(1-1/zoom)*on/{d}'"
            f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    # fallback
    return (
        f"zoompan=z='min(zoom+0.0008,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={d}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


def image_to_video(
    image_path: Path,
    duration: float,
    output_path: Path,
    motion: str = "zoom_in",
) -> Path:
    """Convert a static image to a video clip with Ken Burns motion effect."""
    zoom_filter = _kenburns_filter(motion, duration)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-vf", zoom_filter,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    _run(cmd, "image_to_video")
    return output_path


# ── Concat ────────────────────────────────────────────────────────────────────

_TRANSITION_TYPES = [
    "fade", "fadeblack", "wipeleft", "wiperight", "slideleft", "slideright",
]


def concat_with_transitions(
    video_paths: list[Path],
    durations: list[float],
    output_path: Path,
    transition_duration: float = 0.5,
) -> Path:
    """Concatenate video clips with random xfade transitions between each pair."""
    if len(video_paths) == 1:
        shutil.copy2(video_paths[0], output_path)
        return output_path

    n = len(video_paths)
    inputs: list[str] = []
    for p in video_paths:
        inputs += ["-i", str(p)]

    filter_parts: list[str] = []
    cumulative = 0.0
    in_label = "[0:v]"
    for i in range(1, n):
        cumulative += durations[i - 1]
        offset = max(0.0, cumulative - i * transition_duration)
        transition = random.choice(_TRANSITION_TYPES)
        out_label = "[vfinal]" if i == n - 1 else f"[v{i}]"
        filter_parts.append(
            f"{in_label}[{i}:v]xfade=transition={transition}"
            f":duration={transition_duration}:offset={offset:.3f}{out_label}"
        )
        in_label = out_label

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vfinal]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    _run(cmd, "concat_transitions")
    return output_path


def concat_videos(video_paths: list[Path], output_path: Path) -> Path:
    """Concatenate video clips using ffmpeg concat demuxer (no transitions)."""
    list_file = output_path.parent / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in video_paths))
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(output_path),
    ]
    _run(cmd, "concat")
    list_file.unlink(missing_ok=True)
    return output_path


def merge_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    """Merge audio track into video, trimming to shortest."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    _run(cmd, "merge_audio")
    return output_path


def concat_audio(audio_paths: list[Path], output_path: Path) -> Path:
    """Concatenate audio files."""
    inputs: list[str] = []
    for p in audio_paths:
        inputs += ["-i", str(p)]
    filter_str = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
    filter_str += f"concat=n={len(audio_paths)}:v=0:a=1[aout]"
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[aout]",
        "-c:a", "libmp3lame",
        str(output_path),
    ]
    _run(cmd, "concat_audio")
    return output_path


def mix_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    music_vol: float = 0.15,
) -> Path:
    """Mix looping background music into video with sidechain ducking.

    The narration sidechains the compressor so music drops when someone speaks
    and returns during silences.
    """
    # Split narration: one copy for output, one for sidechain control
    filter_complex = (
        f"[0:a]asplit[nar1][nar2];"
        f"[1:a]volume={music_vol}[music];"
        f"[music][nar2]sidechaincompress=threshold=0.02:ratio=6:attack=100:release=500[ducked];"
        f"[nar1][ducked]amix=inputs=2:duration=first[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    _run(cmd, "mix_music")
    return output_path


def burn_captions(video_path: Path, subtitle_path: Path, output_path: Path) -> Path:
    """Burn subtitles into video. Handles both ASS and SRT."""
    suffix = subtitle_path.suffix.lower()
    if suffix == ".ass":
        # ASS files carry their own styling — just reference the file
        vf = f"ass={subtitle_path}"
    else:
        style = (
            "FontName=Arial,FontSize=20,Bold=1,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "Outline=2,Shadow=1,Alignment=2,MarginV=80"
        )
        vf = f"subtitles={subtitle_path}:force_style='{style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    _run(cmd, "burn_captions")
    return output_path


def final_encode(video_path: Path, output_path: Path) -> Path:
    """Final encode to YouTube Shorts spec."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        *SHORTS_VIDEO_ARGS,
        str(output_path),
    ]
    _run(cmd, "final_encode")
    return output_path
