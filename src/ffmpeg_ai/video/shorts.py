"""YouTube Shorts constants and helpers."""

from dataclasses import dataclass

@dataclass
class VideoSpec:
    width: int
    height: int
    fps: int = 30
    max_duration: int = 600  # 10 minutes
    aspect: str = "9:16"

    def get_args(self) -> list[str]:
        return [
            "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                   f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black",
            "-r", str(self.fps),
            "-c:v", "libx264",
            "-profile:v", "high",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "256k", # Higher bitrate for longer video
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
        ]

MODES = {
    "shorts": VideoSpec(1080, 1920, aspect="9:16", max_duration=58),
    "landscape": VideoSpec(1920, 1080, aspect="16:9"),
}

FPS = 30
