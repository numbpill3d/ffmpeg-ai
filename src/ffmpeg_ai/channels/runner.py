"""Orchestrate a full channel run: harvest → generate → upload."""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Optional

from ..ai.openrouter import FREE_MODELS
from ..ai.tts import VOICES
from ..auto.harvest import harvest_for_channel, save_seen
from ..auto.youtube import upload_video, is_configured
from ..pipeline import run_pipeline
from ..ui.display import console
from .config import ChannelConfig

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"


def _out_dir(channel: ChannelConfig) -> Path:
    return Path.home() / "Videos" / "ffmpeg-ai" / channel.name


def _load_viral(topic: str) -> dict:
    job_dir = _JOB_CACHE / _slug(topic)
    script_p = job_dir / "script.json"
    if script_p.exists():
        return json.loads(script_p.read_text()).get("viral_package", {})
    return {}


def _do_upload(
    channel: ChannelConfig,
    topic: str,
    out: Path,
    script_title: str,
) -> Optional[str]:
    viral = _load_viral(topic)
    title = script_title or topic
    desc  = viral.get("description") or f"{topic} #{channel.name}"
    tags  = viral.get("hashtags") or [f"#{channel.name}"]
    thumb = out.with_suffix(".thumb.jpg")

    console.print(f"[cyan]uploading:[/] {title}")
    url = upload_video(
        video_path=out,
        title=title,
        description=desc,
        tags=tags,
        thumbnail_path=thumb if thumb.exists() else None,
        privacy=channel.privacy,
        category_id=channel.category_id,
        secrets_path=channel.secrets_path,
        token_path=channel.token_path,
    )
    return url


async def _get_script_title(topic: str) -> str:
    job_dir = _JOB_CACHE / _slug(topic)
    script_p = job_dir / "script.json"
    if script_p.exists():
        return json.loads(script_p.read_text()).get("title", topic)
    return topic


async def run_channel(
    channel: ChannelConfig,
    shorts: bool = True,
    landscape: bool = True,
    upload: bool | None = None,
    count: int = 1,
    quiet: bool = False,
    model: str = FREE_MODELS[0],
) -> dict:
    """Run a full channel cycle. Returns summary dict."""
    should_upload = upload if upload is not None else channel.upload
    out_dir = _out_dir(channel)
    out_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold cyan]channel:[/] {channel.display_name}")
    console.print(f"  niche:   {channel.niche[:60]}")
    console.print(f"  style:   {channel.style}   voice: {channel.voice}")
    console.print(f"  upload:  {should_upload}")

    # Topic harvest
    console.print(f"\n[bold cyan]harvesting {count} topic(s)…[/]")
    topics = await harvest_for_channel(
        sources=channel.sources,
        niche=channel.niche,
        audience=channel.audience,
        count=count,
        channel_name=channel.name,
    )

    if not topics:
        console.print("[bold red]no topics harvested — try again later[/]")
        return {"channel": channel.name, "topics": [], "generated": [], "uploaded": []}

    console.print("[green]topics:[/]")
    for t in topics:
        console.print(f"  • {t}")

    save_seen(topics, channel_name=channel.name)

    selected_voice = VOICES.get(channel.voice, channel.voice)
    generated: list[dict] = []

    for topic in topics:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")

        if shorts:
            console.print(f"\n[bold cyan]── short: {topic} ──[/]")
            out = out_dir / f"{ts}_{slug}_short.mp4"
            try:
                await run_pipeline(
                    topic=topic,
                    output_path=out,
                    mode="shorts",
                    duration=channel.shorts_duration,
                    model=model,
                    voice=selected_voice,
                    style=channel.style,
                    quiet=quiet,
                    thumbnail=True,
                )
                title = await _get_script_title(topic)
                entry = {"topic": topic, "mode": "short", "path": str(out), "url": None}
                if should_upload and is_configured(channel.secrets_path, channel.token_path):
                    try:
                        url = _do_upload(channel, topic, out, title)
                        entry["url"] = url
                        console.print(f"[bold green]✓[/] {url}")
                    except Exception as e:
                        console.print(f"[bold red]✗[/] upload failed: {e}")
                generated.append(entry)
            except Exception as e:
                console.print(f"[bold red]✗[/] short failed: {e}")

        if landscape:
            console.print(f"\n[bold cyan]── long-form: {topic} ──[/]")
            out_l = out_dir / f"{ts}_{slug}_landscape.mp4"
            try:
                await run_pipeline(
                    topic=topic,
                    output_path=out_l,
                    mode="landscape",
                    duration=channel.landscape_duration,
                    model=model,
                    voice=selected_voice,
                    style=channel.style,
                    quiet=quiet,
                    thumbnail=True,
                    fresh=True,
                )
                title = await _get_script_title(topic)
                entry = {"topic": topic, "mode": "landscape", "path": str(out_l), "url": None}
                if should_upload and is_configured(channel.secrets_path, channel.token_path):
                    try:
                        url = _do_upload(channel, topic, out_l, title)
                        entry["url"] = url
                        console.print(f"[bold green]✓[/] {url}")
                    except Exception as e:
                        console.print(f"[bold red]✗[/] upload failed: {e}")
                generated.append(entry)
            except Exception as e:
                console.print(f"[bold red]✗[/] landscape failed: {e}")

    uploaded = [g for g in generated if g.get("url")]
    console.print(
        f"\n[bold green]done[/] — {len(generated)} video(s) generated"
        + (f", {len(uploaded)} uploaded" if should_upload else "")
    )
    return {
        "channel": channel.name,
        "topics": topics,
        "generated": generated,
        "uploaded": uploaded,
    }
