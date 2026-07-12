from ffmpeg_ai.channels.config import ChannelConfig


def _valid_channel(**overrides) -> ChannelConfig:
    data = {
        "name": "test",
        "display_name": "Test Channel",
        "niche": "testing",
        "audience": "builders",
        "style": "educational",
        "voice": "en-female",
        "sources": ["reddit:technology"],
    }
    data.update(overrides)
    return ChannelConfig(**data)


def test_channel_config_validates_accent_color() -> None:
    errors = _valid_channel(accent_color="cyan").validate()

    assert any("accent_color" in error for error in errors)


def test_channel_config_accepts_hex_accent_color() -> None:
    assert _valid_channel(accent_color="#00d4ff").validate() == []
