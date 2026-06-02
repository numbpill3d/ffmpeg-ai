"""Orchestrate a full channel run: harvest → generate → upload → log."""
from __future__ import annotations

import asyncio
import datetime
import json
import re
from pathlib import Path
from typing import Optional

from ..ai.openrouter import FREE_MODELS
from ..ai.tts import VOICES
from ..auto.harvest import harvest_for_channel, save_seen
from ..auto.youtube import next_publish_time, upload_video
from ..pipeline import run_pipeline
from ..ui.display import console
from .config import ChannelConfig

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"


def _out_dir(channel: ChannelConfig) -> Path:
    return Path.home() / "Videos" / "ffmpeg-ai" / channel.name


def _load_script(topic: str) -> dict:
    return json.loads((_JOB_CACHE / _slug(topic) / "script.json").read_text())


def _script_title(topic: str) -> str:
    try:
        return _load_script(topic).get("title", topic)
    except Exception:
        return topic


def _viral(topic: str) -> dict:
    try:
        return _load_script(topic).get("viral_package", {})
    except Exception:
        return {}


# ── Run logging ───────────────────────────────────────────────────────────────

def _append_run_log(channel: ChannelConfig, entry: dict) -> None:
    channel.run_log_path.parent.mkdir(parents=True, exist_ok=True)
    with channel.run_log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def read_run_log(channel: ChannelConfig, limit: int = 20) -> list[dict]:
    """Return the most recent `limit` run entries for a channel."""
    if not channel.run_log_path.exists():
        return []
    lines = channel.run_log_path.read_text().splitlines()
    entries: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
        if len(entries) >= limit:
            break
    return entries


# ── Upload (blocking → async via thread) ─────────────────────────────────────

async def _upload(
    channel: ChannelConfig,
    topic: str,
    out: Path,
) -> Optional[str]:
    """Non-blocking upload. Returns URL or None on failure."""
    viral = _viral(topic)
    title = _script_title(topic)
    desc  = viral.get("description") or f"{topic} #{channel.name}"
    tags  = viral.get("hashtags") or [f"#{channel.name}"]
    thumb = out.with_suffix(".thumb.jpg")

    publish_at: Optional[datetime.datetime] = None
    if channel.publish_hour is not None and channel.privacy == "public":
        publish_at = next_publish_time(channel.publish_hour)

    console.print(f"[cyan]uploading:[/] {title}")
    if publish_at:
        console.print(f"[dim]  scheduled publish: {publish_at.strftime('%Y-%m-%d %H:%M UTC')}[/]")

    try:
        url = await asyncio.to_thread(
            upload_video,
            video_path=out,
            title=title,
            description=desc,
            tags=tags,
            thumbnail_path=thumb if thumb.exists() else None,
            privacy=channel.privacy,
            category_id=channel.category_id,
            secrets_path=channel.secrets_path,
            token_path=channel.token_path,
            publish_at=publish_at,
        )
        console.print(f"[bold green]✓[/] {url}")
        return url
    except Exception as e:
        console.print(f"[bold red]✗[/] upload failed: {e}")
        return None


# ── Single video generation ───────────────────────────────────────────────────

async def _generate_one(
    channel: ChannelConfig,
    topic: str,
    mode: str,
    out: Path,
    model: str,
    quiet: bool,
    fresh: bool,
) -> bool:
    """Generate one video. Returns True on success."""
    selected_voice = VOICES.get(channel.voice, channel.voice)
    duration = channel.shorts_duration if mode == "shorts" else channel.landscape_duration
    label = "short" if mode == "shorts" else "long-form"
    console.print(f"\n[bold cyan]── {label}: {topic} ──[/]")
    try:
        await run_pipeline(
            topic=topic,
            output_path=out,
            mode=mode,
            duration=duration,
            model=model,
            voice=selected_voice,
            style=channel.style,
            quiet=quiet,
            thumbnail=True,
            fresh=fresh,
        )
        return True
    except Exception as e:
        console.print(f"[bold red]✗[/] {label} generation failed: {e}")
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_channel(
    channel: ChannelConfig,
    shorts: bool = True,
    landscape: bool = True,
    upload: Optional[bool] = None,
    count: int = 1,
    quiet: bool = False,
    model: str = FREE_MODELS[0],
    dry_run: bool = False,
) -> dict:
    """Run a full channel cycle. Returns a summary dict."""
    should_upload = upload if upload is not None else channel.upload
    out_dir = _out_dir(channel)

    console.print(f"\n[bold cyan]channel:[/] {channel.display_name}")
    console.print(f"  niche:  {channel.niche[:70]}")
    console.print(f"  style:  {channel.style}   voice: {channel.voice}")
    if should_upload:
        status = (
            "[green]enabled[/]" if channel.is_youtube_configured
            else "[yellow]enabled but YouTube not configured[/]"
        )
        console.print(f"  upload: {status}")
    else:
        console.print("  upload: [dim]disabled[/]")

    # ── Topic harvest ─────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]harvesting {count} topic(s)…[/]")
    start = datetime.datetime.now()

    topics = await harvest_for_channel(
        sources=channel.sources,
        niche=channel.niche,
        audience=channel.audience,
        count=count,
        channel_name=channel.name,
    )

    if not topics:
        console.print("[bold red]no topics harvested — all sources returned nothing[/]")
        return {"channel": channel.name, "topics": [], "generated": [], "uploaded": []}

    console.print("[green]topics:[/]")
    for t in topics:
        console.print(f"  • {t}")

    if dry_run:
        console.print("\n[dim]dry-run — stopping before generation[/]")
        return {"channel": channel.name, "topics": topics, "generated": [], "uploaded": []}

    save_seen(topics, channel_name=channel.name)

    out_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict] = []

    for topic in topics:
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")

        # Short first — uses a fresh script (new generation each run)
        if shorts:
            out = out_dir / f"{ts}_{slug}_short.mp4"
            ok  = await _generate_one(
                channel, topic, "shorts", out, model, quiet, fresh=True,
            )
            if ok:
                url = await _upload(channel, topic, out) if (
                    should_upload and channel.is_youtube_configured
                ) else None
                generated.append({
                    "topic": topic, "mode": "short",
                    "path": str(out), "url": url,
                    "ts": ts,
                })

        # Landscape second — must be fresh so the pipeline generates the longer script
        # rather than reusing the shorts-format script.json from the same topic slug.
        if landscape:
            out_l = out_dir / f"{ts}_{slug}_landscape.mp4"
            ok    = await _generate_one(
                channel, topic, "landscape", out_l, model, quiet, fresh=True,
            )
            if ok:
                url = await _upload(channel, topic, out_l) if (
                    should_upload and channel.is_youtube_configured
                ) else None
                generated.append({
                    "topic": topic, "mode": "landscape",
                    "path": str(out_l), "url": url,
                    "ts": ts,
                })

    uploaded = [g for g in generated if g.get("url")]
    elapsed  = (datetime.datetime.now() - start).seconds

    console.print(
        f"\n[bold green]done[/] — {len(generated)} video(s) in {elapsed}s"
        + (f", {len(uploaded)} uploaded" if should_upload else "")
    )

    run_entry = {
        "timestamp":  datetime.datetime.now().isoformat(),
        "channel":    channel.name,
        "topics":     topics,
        "generated":  generated,
        "uploaded":   uploaded,
        "elapsed_s":  elapsed,
    }
    _append_run_log(channel, run_entry)

    return run_entry
