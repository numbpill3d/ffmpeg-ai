import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.exceptions import Exit

from ffmpeg_ai import cli
from ffmpeg_ai import pipeline


def test_batch_uses_one_event_loop_for_multiple_topics(tmp_path: Path, monkeypatch) -> None:
    topics_file = tmp_path / "topics.txt"
    topics_file.write_text("alpha\nbeta\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    calls: list[str] = []

    async def fake_run_pipeline(*, topic: str, **kwargs):
        calls.append(topic)
        return tmp_path / f"{topic}.mp4"

    original_run = asyncio.run
    run_count = 0

    def counting_run(coro):
        nonlocal run_count
        run_count += 1
        return original_run(coro)

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(cli.asyncio, "run", counting_run)

    cli.batch(
        topics_file=topics_file,
        output_dir=tmp_path / "out",
        mode="shorts",
        duration=45,
        model="test-model",
        voice="en-female",
        style=None,
        caption_style="karaoke",
        no_thumbnail=False,
        no_ambience=False,
        fresh=False,
        quiet=True,
        brand_name="",
        accent_color="#00d4ff",
    )

    assert calls == ["alpha", "beta"]
    assert run_count == 1


def test_auto_uses_one_event_loop_for_harvest_and_generation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    harvested = ["alpha topic", "beta topic"]
    generated: list[str] = []
    saved: list[list[str]] = []

    async def fake_harvest(*, count: int):
        return harvested[:count]

    def fake_save_seen(topics):
        saved.append(list(topics))

    async def fake_run_pipeline(*, topic: str, **kwargs):
        generated.append(topic)
        out = kwargs["output_path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("ok", encoding="utf-8")
        return out

    original_run = asyncio.run
    run_count = 0

    def counting_run(coro):
        nonlocal run_count
        run_count += 1
        return original_run(coro)

    import ffmpeg_ai.auto.harvest as harvest_mod

    monkeypatch.setattr(harvest_mod, "harvest", fake_harvest)
    monkeypatch.setattr(harvest_mod, "save_seen", fake_save_seen)
    monkeypatch.setattr(pipeline, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(cli.asyncio, "run", counting_run)

    cli.auto(
        count=2,
        upload=False,
        privacy="public",
        style=None,
        voice="en-female",
        dry_run=False,
        quiet=True,
        brand_name="",
        accent_color="#00d4ff",
    )

    assert generated == harvested
    assert saved == [harvested]
    assert run_count == 1


@dataclass
class _ChannelStub:
    name: str
    display_name: str

    def validate(self) -> list[str]:
        return []


def test_channel_run_uses_one_event_loop_for_multiple_channels(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    channels = {
        "alpha": _ChannelStub(name="alpha", display_name="Alpha"),
        "beta": _ChannelStub(name="beta", display_name="Beta"),
    }
    calls: list[str] = []

    async def fake_run_channel(*, channel, **kwargs):
        calls.append(channel.name)
        return {"channel": channel.name}

    original_run = asyncio.run
    run_count = 0

    def counting_run(coro):
        nonlocal run_count
        run_count += 1
        return original_run(coro)

    import ffmpeg_ai.channels.config as config_mod
    import ffmpeg_ai.channels.runner as runner_mod

    monkeypatch.setattr(config_mod.ChannelConfig, "list_all", classmethod(lambda cls: list(channels)))
    monkeypatch.setattr(config_mod.ChannelConfig, "load", classmethod(lambda cls, name: channels[name]))
    monkeypatch.setattr(runner_mod, "run_channel", fake_run_channel)
    monkeypatch.setattr(cli.asyncio, "run", counting_run)

    cli.channel_run(name=None, shorts=True, landscape=True, upload=False, count=1, model="test-model", quiet=True, dry_run=False)

    assert calls == ["alpha", "beta"]
    assert run_count == 1


def test_parse_provider_list_rejects_unknown_image_provider() -> None:
    with pytest.raises(Exit):
        cli._parse_provider_list("pollinations,nope")


def test_validate_hex_color_rejects_invalid_accent_color() -> None:
    with pytest.raises(Exit):
        cli._validate_hex_color("blue")
