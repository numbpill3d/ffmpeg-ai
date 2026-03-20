"""YouTube Shorts constants and helpers."""

# Target spec
WIDTH = 1080
HEIGHT = 1920
FPS = 30
MAX_DURATION = 58  # seconds — safe margin under 60s
ASPECT = "9:16"

# ffmpeg base video args for Shorts output
SHORTS_VIDEO_ARGS = [
    "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
           f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
    "-r", str(FPS),
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "44100",
    "-ac", "2",
    "-movflags", "+faststart",
]

def clamp_duration(seconds: float) -> float:
    return min(seconds, MAX_DURATION)
