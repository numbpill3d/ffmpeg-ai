"""Multi-channel automation for ffmpeg-ai."""
from .config import CHANNELS_DIR, ChannelConfig, PRESETS
from .runner import read_run_log, run_channel

__all__ = ["ChannelConfig", "CHANNELS_DIR", "PRESETS", "run_channel", "read_run_log"]
