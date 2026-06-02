"""Multi-channel automation for ffmpeg-ai."""
from .config import ChannelConfig, CHANNELS_DIR, PRESETS
from .runner import run_channel

__all__ = ["ChannelConfig", "CHANNELS_DIR", "PRESETS", "run_channel"]
