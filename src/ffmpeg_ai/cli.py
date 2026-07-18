"""CLI entry point."""
from __future__ import annotations

import asyncio
import datetime
import os
import re
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .ui.display import (
    C_ACCENT, C_DIM, C_ERROR, C_MUTED, C_SUCCESS,
    bullet, console, error, header, info, print_banner, success, warn,
)
from .ai.images import _ALL_PROVIDERS
from .ai.openrouter import FREE_MODELS, STYLE_PRESETS
from .ai.tts import VOICES, STYLE_VOICE_MAP
from .video.shorts import MODES

load_dotenv()

_JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"

app = typer.Typer(
    name="ffmpeg-ai",
    help="AI-powered YouTube video automation",
    rich_markup_mode="rich",
    invoke_without_command=True,
    add_completion=False,
)

_STYLE_CHOICES   = list(STYLE_PRESETS.keys())
_CAPTION_CHOICES = ["karaoke", "plain", "bold-center"]
_RENDER_CHOICES = ["kenburns", "storyboard", "fast-preview"]


def _run_async(coro):
    return asyncio.run(coro)


def _validate_hex_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        error(f"invalid hex color '{value}' — expected format like #00d4ff")
        raise typer.Exit(1)
    return value


def _parse_provider_list(providers: Optional[str]) -> Optional[list[str]]:
    if providers is None:
        return None
    selected = [p.strip() for p in providers.split(",") if p.strip()]
    if not selected:
        error("--providers was supplied but no provider names were found")
        raise typer.Exit(1)
    unknown = [p for p in selected if p not in _ALL_PROVIDERS]
    if unknown:
        error(
            f"unknown provider(s): {', '.join(unknown)} — choose from: "
            f"{', '.join(_ALL_PROVIDERS)}"
        )
        raise typer.Exit(1)
    return selected


async def _run_batch_async(
    *,
    topics: list[str],
    out_dir: Path,
    mode: str,
    duration: int,
    model: str,
    voice: str,
    style: Optional[str],
    caption_style: str,
    render_mode: Optional[str],
    no_thumbnail: bool,
    no_ambience: bool,
    no_hook: bool = False,
    font_path: Optional[str] = None,
    fresh: bool,
    quiet: bool,
    brand_name: str,
    accent_color: str,
) -> int:
    from .pipeline import run_pipeline

    failed = 0
    for i, topic in enumerate(topics, 1):
        console.print()
        console.print(Rule(
            f"[{C_ACCENT}]{i}/{len(topics)}[/]  {topic}",
            style=C_DIM,
        ))
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")
        out = out_dir / f"{ts}_{slug}.mp4"
        try:
            await run_pipeline(
                topic=topic,
                output_path=out,
                mode=mode,
                duration=min(duration, 600),
                model=model,
                voice=voice,
                style=style,
                caption_style=caption_style,
                render_mode=render_mode,
                thumbnail=not no_thumbnail,
                no_ambience=no_ambience,
                no_hook=no_hook,
                font_path=font_path,
                fresh=fresh,
                quiet=quiet,
                brand_name=brand_name,
                accent_color=accent_color,
            )
        except Exception as e:
            error(f"topic {i} failed: {e}")
            failed += 1
    return failed


async def _run_auto_async(
    *,
    count: int,
    upload: bool,
    privacy: str,
    style: Optional[str],
    voice: str,
    quiet: bool,
    dry_run: bool,
    brand_name: str,
    accent_color: str,
) -> None:
    import json as _json
    from .auto.harvest import harvest, save_seen
    from .auto.youtube import upload_video, is_configured
    from .pipeline import run_pipeline

    header("harvesting topics", f"count={count}")
    topics = await harvest(count=count)

    if not topics:
        error("no topics found — try again later")
        raise typer.Exit(1)

    for topic in topics:
        bullet(topic)

    if dry_run:
        info("dry-run — stopping before generation")
        return

    save_seen(topics)

    out_dir = Path.home() / "Videos" / "ffmpeg-ai" / "auto"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated: list[tuple[str, Path]] = []
    for i, topic in enumerate(topics, 1):
        console.print()
        console.print(Rule(
            f"[{C_ACCENT}]{i}/{len(topics)}[/]  {topic}",
            style=C_DIM,
        ))
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")
        out = out_dir / f"{ts}_{slug}.mp4"
        try:
            await run_pipeline(
                topic=topic,
                output_path=out,
                mode="shorts",
                duration=45,
                voice=voice,
                style=style,
                quiet=quiet,
                thumbnail=True,
                brand_name=brand_name,
                accent_color=accent_color,
            )
            generated.append((topic, out))
        except Exception as e:
            error(str(e))

    if not upload:
        console.print()
        success(f"{len(generated)} Short(s) in {out_dir}")
        info("add --upload to auto-publish to YouTube")
        return

    if not is_configured():
        warn("YouTube not configured — run: ffmpeg-ai youtube-setup")
        return

    uploaded = 0
    console.print()
    console.print(Rule(f"[{C_ACCENT}]uploading[/]", style=C_DIM))

    for topic, out in generated:
        job_slug = re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"
        script_p = _JOB_CACHE / job_slug / "script.json"
        script = _json.loads(script_p.read_text()) if script_p.exists() else {}
        viral = script.get("viral_package", {})
        title = script.get("title") or topic
        desc = viral.get("description") or f"{topic} #shorts"
        tags = viral.get("hashtags") or ["#shorts", "#tech"]
        thumb = out.with_suffix(".thumb.jpg")

        info(f"uploading: {title}")
        try:
            url = upload_video(
                video_path=out,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_path=thumb if thumb.exists() else None,
                privacy=privacy,
            )
            success(url)
            uploaded += 1
        except Exception as e:
            error(f"upload failed: {e}")

    console.print()
    success(f"{uploaded}/{len(generated)} uploaded")


async def _run_channels_async(
    *,
    channel_names: list[str],
    shorts: bool,
    landscape: bool,
    upload: Optional[bool],
    count: int,
    model: str,
    quiet: bool,
    dry_run: bool,
) -> None:
    from .channels.config import ChannelConfig
    from .channels.runner import run_channel

    for ch_name in channel_names:
        try:
            ch = ChannelConfig.load(ch_name)
        except FileNotFoundError as e:
            error(str(e))
            continue
        errs = ch.validate()
        if errs:
            for e in errs:
                error(f"config error ({ch_name}): {e}")
            continue
        await run_channel(
            channel=ch,
            shorts=shorts,
            landscape=landscape,
            upload=upload,
            count=count,
            quiet=quiet,
            model=model,
            dry_run=dry_run,
        )


# ── Help screen ───────────────────────────────────────────────────────────────

def _help_commands() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    t.add_column("cmd",  style=f"bold {C_ACCENT}", no_wrap=True, min_width=14)
    t.add_column("desc", style="white")

    rows = [
        ("generate",  "create a video from a topic"),
        ("batch",     "generate from a file of topics"),
        ("auto",      "harvest trending topics → generate → upload"),
        ("channel",   "manage automated multi-channel pipeline"),
        ("",          ""),
        ("models",    "list free LLM models"),
        ("voices",    "list TTS voices"),
        ("providers", "list image providers + auth status"),
    ]
    for cmd, desc in rows:
        if not cmd:
            t.add_row("", f"[{C_DIM}]──────────────────────────────────[/]")
        else:
            t.add_row(cmd, desc)
    return Panel(t, title=f"[bold {C_ACCENT}]commands[/]", border_style=C_DIM, box=box.ROUNDED)


def _help_flags() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column("flag",    style=f"bold {C_ACCENT}", no_wrap=True, min_width=18)
    t.add_column("default", style="yellow",           no_wrap=True, min_width=10)
    t.add_column("desc",    style="white")

    rows = [
        ("TOPIC",             "required",  "topic or idea for the video"),
        ("--mode",            "shorts",    "shorts (9:16)  landscape (16:9)"),
        ("--style",           "–",         f"{', '.join(_STYLE_CHOICES)}"),
        ("--voice  -v",       "en-female", "TTS voice  (see: voices)"),
        ("--duration  -d",    "45 / 600",  "target seconds  (max 600)"),
        ("--output  -o",      "~/Videos/", "output .mp4 path"),
        ("--model  -m",       "auto",      "OpenRouter model ID  (see: models)"),
        ("--music  -M",       "–",         "background music, auto-ducked"),
        ("--images-dir  -I",  "–",         "use local images instead of AI"),
        ("--script",          "–",         "load script JSON, skip LLM"),
        ("--caption-style",   "karaoke",   "karaoke  plain  bold-center"),
        ("--render-mode",     "auto",      "kenburns  storyboard  fast-preview"),
        ("--providers",       "all",       "provider order: pollinations,hf,..."),
        ("--brand-name",      "–",         "channel name for thumbnail branding"),
        ("--accent-color",    "#c084ff",   "hex color for thumbnail accent bar"),
        ("--edit-script",     "off",       "open script in $EDITOR before render"),
        ("--fresh",           "off",       "ignore all cached job data"),
        ("--dry-run",         "off",       "script only, no video rendered"),
        ("--no-captions",     "off",       "skip whisper + caption burn"),
        ("--no-thumbnail",    "off",       "skip thumbnail extraction"),
        ("--no-ambience",     "off",       "skip background ambience layer"),
        ("-q / --quiet",      "off",       "minimal output, one line per stage"),
    ]
    for flag, default, desc in rows:
        t.add_row(flag, default, desc)
    return Panel(
        t, title=f"[bold {C_ACCENT}]generate — flags[/]", border_style=C_DIM, box=box.ROUNDED
    )


def _help_examples() -> Panel:
    t = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    t.add_column("label", style=C_MUTED,         no_wrap=True, min_width=20)
    t.add_column("cmd",   style=f"bold {C_SUCCESS}")

    rows = [
        ("shorts (default)",    'ffmpeg-ai generate "5 facts about black holes"'),
        ("long-form",           'ffmpeg-ai generate "history of Rome" --mode landscape'),
        ("with style",          'ffmpeg-ai generate "deep sea" --style dramatic'),
        ("edit before render",  'ffmpeg-ai generate "mars" --edit-script'),
        ("batch from file",     "ffmpeg-ai batch topics.txt -o ~/Videos/batch/"),
        ("auto-pilot (tech)",   "ffmpeg-ai auto --count 3"),
        ("channel automation",  "ffmpeg-ai channel run history"),
        ("run all channels",    "ffmpeg-ai channel run"),
    ]
    for label, cmd in rows:
        t.add_row(label, cmd)
    return Panel(t, title=f"[bold {C_ACCENT}]examples[/]", border_style=C_DIM, box=box.ROUNDED)


def _help_env() -> Panel:
    has = lambda k: "[bold green]✓[/]" if os.environ.get(k) else f"[{C_MUTED}]–[/]"  # noqa: E731
    badge_req  = f"[bold {C_ERROR}]required[/]"
    badge_free = f"[dim {C_SUCCESS}]free    [/]"
    badge_paid = "[dim yellow]paid    [/]"

    t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    t.add_column("set",  no_wrap=True, width=3)
    t.add_column("var",  style=f"bold {C_ACCENT}", no_wrap=True, min_width=22)
    t.add_column("type", no_wrap=True, min_width=10)
    t.add_column("desc", style="white")

    rows = [
        ("OPENROUTER_API_KEY",   badge_req,  "LLM script generation"),
        ("HF_TOKEN",             badge_free, "HuggingFace image fallback"),
        ("STABLE_HORDE_API_KEY", badge_free, "community GPU cluster"),
        ("TOGETHER_API_KEY",     badge_free, "Together AI FLUX schnell"),
        ("BFL_API_KEY",          badge_paid, "Black Forest Labs"),
        ("FAL_KEY",              badge_paid, "Fal.ai Flux Dev"),
        ("PRODIA_TOKEN",         badge_paid, "Prodia Flux Schnell"),
    ]
    for var, badge, desc in rows:
        t.add_row(has(var), var, badge, desc)
    return Panel(
        t,
        title=f"[bold {C_ACCENT}]env vars[/]  [dim](.env supported)[/]",
        border_style=C_DIM,
        box=box.ROUNDED,
    )


@app.callback()
def main(ctx: typer.Context) -> None:
    """AI-powered YouTube video automation."""
    if ctx.invoked_subcommand is not None:
        return
    print_banner()
    console.print()
    console.print(Columns([_help_commands(), _help_flags()], equal=False, expand=True))
    console.print()
    console.print(Columns([_help_examples(), _help_env()], equal=False, expand=True))
    console.print()


# ── generate ──────────────────────────────────────────────────────────────────

@app.command()
def generate(
    topic: str = typer.Argument(..., help="Topic or idea for the video"),
    mode: str = typer.Option("shorts", help="shorts (9:16) or landscape (16:9)"),
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
    duration: Optional[int] = typer.Option(
        None, "-d", "--duration",
        help="Target duration in seconds (defaults: 45 shorts, 600 landscape)",
    ),
    model: str   = typer.Option(FREE_MODELS[0], "-m", "--model"),
    voice: str   = typer.Option("en-female", "-v", "--voice"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    images_dir: Optional[Path] = typer.Option(None, "--images-dir", "-I"),
    no_ai_images: bool = typer.Option(False, "--no-ai-images"),
    providers: Optional[str] = typer.Option(None, "--providers"),
    music: Optional[Path]    = typer.Option(None, "--music", "-M"),
    script: Optional[Path]   = typer.Option(None, "--script"),
    edit_script: bool  = typer.Option(False, "--edit-script"),
    fresh: bool        = typer.Option(False, "--fresh"),
    quiet: bool        = typer.Option(False, "-q", "--quiet"),
    no_thumbnail: bool = typer.Option(False, "--no-thumbnail"),
    style: Optional[str] = typer.Option(None, "--style"),
    caption_style: str   = typer.Option("karaoke", "--caption-style"),
    render_mode: Optional[str] = typer.Option(None, "--render-mode"),
    no_captions: bool    = typer.Option(False, "--no-captions"),
    no_ambience: bool    = typer.Option(False, "--no-ambience"),
    no_hook: bool        = typer.Option(False, "--no-hook", help="Skip the hook text overlay (Windows-safe)"),
    font: Optional[Path] = typer.Option(None, "--font", help="Explicit .ttf path for overlays/captions"),
    brand_name: str      = typer.Option("", "--brand-name", help="Channel name for thumbnail branding"),
    accent_color: str    = typer.Option("#c084ff", "--accent-color", help="Hex color for thumbnail accent bar"),
):
    """[bold magenta]Generate a video from a topic string.[/]"""
    print_banner()

    if not os.environ.get("OPENROUTER_API_KEY", "") and script is None:
        error("OPENROUTER_API_KEY not set — add it to .env or export it")
        raise typer.Exit(1)

    if mode not in MODES:
        error(f"unknown mode '{mode}' — choose from: {', '.join(MODES)}")
        raise typer.Exit(1)

    if duration is None:
        duration = 600 if mode == "landscape" else 45

    if style and style not in _STYLE_CHOICES:
        error(f"unknown style '{style}' — choose from: {', '.join(_STYLE_CHOICES)}")
        raise typer.Exit(1)

    if caption_style not in _CAPTION_CHOICES:
        error(f"unknown caption-style '{caption_style}' — choose from: {', '.join(_CAPTION_CHOICES)}")  # noqa: E501
        raise typer.Exit(1)

    render_mode = render_mode if isinstance(render_mode, str) else None
    if render_mode is not None and render_mode not in _RENDER_CHOICES:
        error(f"unknown render-mode '{render_mode}' — choose from: {', '.join(_RENDER_CHOICES)}")
        raise typer.Exit(1)

    accent_color = _validate_hex_color(accent_color)

    if images_dir is not None and not images_dir.is_dir():
        error(f"--images-dir not found: {images_dir}")
        raise typer.Exit(1)

    if script is not None and not script.is_file():
        error(f"--script file not found: {script}")
        raise typer.Exit(1)

    if music is not None and not music.is_file():
        error(f"--music file not found: {music}")
        raise typer.Exit(1)

    if output is None:
        ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path.home() / "Videos" / "ffmpeg-ai" / f"{ts}.mp4"

    provider_list = _parse_provider_list(providers)

    from .pipeline import run_pipeline
    _run_async(run_pipeline(
        topic=topic,
        mode=mode,
        output_path=output,
        duration=min(duration, 600),
        model=model,
        voice=VOICES.get(voice, voice),
        dry_run=dry_run,
        images_dir=images_dir,
        use_ai_images=not no_ai_images,
        image_providers=provider_list,
        music_path=music,
        script_path=script,
        edit_script=edit_script,
        fresh=fresh,
        quiet=quiet,
        thumbnail=not no_thumbnail,
        style=style,
        caption_style=caption_style,
        render_mode=render_mode,
        no_captions=no_captions,
        no_ambience=no_ambience,
        no_hook=no_hook,
        font_path=str(font) if font else None,
        brand_name=brand_name,
        accent_color=accent_color,
    ))


# ── batch ─────────────────────────────────────────────────────────────────────

@app.command()
def batch(
    topics_file: Path = typer.Argument(
        ..., help="Text file with one topic per line (# lines are comments)"
    ),
    output_dir: Optional[Path] = typer.Option(None, "-o", "--output-dir"),
    mode: str          = typer.Option("shorts"),
    duration: Optional[int] = typer.Option(None, "-d", "--duration"),
    model: str         = typer.Option(FREE_MODELS[0], "-m", "--model"),
    voice: str         = typer.Option("en-female", "-v", "--voice"),
    style: Optional[str]   = typer.Option(None, "--style"),
    caption_style: str     = typer.Option("karaoke", "--caption-style"),
    render_mode: Optional[str] = typer.Option(None, "--render-mode"),
    no_thumbnail: bool = typer.Option(False, "--no-thumbnail"),
    no_ambience: bool  = typer.Option(False, "--no-ambience"),
    no_hook: bool      = typer.Option(False, "--no-hook", help="Skip the hook text overlay (Windows-safe)"),
    font: Optional[Path] = typer.Option(None, "--font", help="Explicit .ttf path for overlays/captions"),
    fresh: bool        = typer.Option(False, "--fresh"),
    quiet: bool        = typer.Option(False, "-q", "--quiet"),
    brand_name: str    = typer.Option("", "--brand-name", help="Channel name for thumbnail branding"),
    accent_color: str  = typer.Option("#c084ff", "--accent-color", help="Hex color for thumbnail accent bar"),
):
    """[bold magenta]Generate multiple videos from a file of topics (one per line).[/]"""
    if not os.environ.get("OPENROUTER_API_KEY", ""):
        error("OPENROUTER_API_KEY not set")
        raise typer.Exit(1)

    if mode not in MODES:
        error(f"unknown mode '{mode}' — choose from: {', '.join(MODES)}")
        raise typer.Exit(1)

    if style and style not in _STYLE_CHOICES:
        error(f"unknown style '{style}' — choose from: {', '.join(_STYLE_CHOICES)}")
        raise typer.Exit(1)

    if caption_style not in _CAPTION_CHOICES:
        error(f"unknown caption-style '{caption_style}' — choose from: {', '.join(_CAPTION_CHOICES)}")  # noqa: E501
        raise typer.Exit(1)

    render_mode = render_mode if isinstance(render_mode, str) else None
    if render_mode is not None and render_mode not in _RENDER_CHOICES:
        error(f"unknown render-mode '{render_mode}' — choose from: {', '.join(_RENDER_CHOICES)}")
        raise typer.Exit(1)

    accent_color = _validate_hex_color(accent_color)

    if not topics_file.is_file():
        error(f"file not found: {topics_file}")
        raise typer.Exit(1)

    if duration is None:
        duration = 600 if mode == "landscape" else 45

    topics = [
        ln.strip()
        for ln in topics_file.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not topics:
        error("no topics found in file")
        raise typer.Exit(1)

    out_dir = output_dir or (Path.home() / "Videos" / "ffmpeg-ai")
    out_dir.mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(Rule(
        f"[bold {C_ACCENT}]batch[/]  [dim]{len(topics)} topics → {out_dir}[/]", style=C_DIM,
    ))

    selected_voice = VOICES.get(voice, voice)
    failed = _run_async(_run_batch_async(
        topics=topics,
        out_dir=out_dir,
        mode=mode,
        duration=duration,
        model=model,
        voice=selected_voice,
        style=style,
        caption_style=caption_style,
        render_mode=render_mode,
        no_thumbnail=no_thumbnail,
        no_ambience=no_ambience,
        no_hook=no_hook,
        font_path=str(font) if font else None,
        fresh=fresh,
        quiet=quiet,
        brand_name=brand_name,
        accent_color=accent_color,
    ))

    console.print()
    if failed == 0:
        success(f"{len(topics)} topics processed — {out_dir}")
    else:
        warn(f"{len(topics) - failed}/{len(topics)} succeeded  ({failed} failed)")


# ── models / voices / providers ───────────────────────────────────────────────

@app.command()
def models() -> None:
    """[dim]List available free OpenRouter LLM models.[/]"""
    console.print()
    t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=False, padding=(0, 2))
    t.add_column("rank",  style=C_MUTED,        no_wrap=True, width=4)
    t.add_column("model", style=f"bold {C_ACCENT}")
    for i, m in enumerate(FREE_MODELS, 1):
        label = "[dim](fast fallback)[/]" if i == len(FREE_MODELS) else ""
        t.add_row(str(i), f"{m}  {label}")
    console.print(Panel(
        t, title=f"[bold {C_ACCENT}]free LLM models[/]", border_style=C_DIM, box=box.ROUNDED,
    ))


@app.command()
def voices() -> None:
    """[dim]List available TTS voices.[/]"""
    console.print()
    t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=True, padding=(0, 1))
    t.add_column("key",      style=f"bold {C_ACCENT}", no_wrap=True, min_width=16)
    t.add_column("voice ID", style="white",            no_wrap=True, min_width=22)
    t.add_column("notes",    style=C_MUTED,            no_wrap=False)

    notes = {
        "en-female":      "general purpose",
        "en-male":        "general purpose",
        "en-news":        "news recap cadence",
        "en-documentary": "authoritative, long-form",
        "en-uk-female":   "British precision",
        "en-energetic":   "fast-paced, punchy",
        "en-storyteller": "narrative warmth",
        "en-au-female":   "Australian accent",
        "en-au-male":     "Australian accent",
        "en-in-female":   "Indian English",
    }
    style_defaults = {v: k for k, v in STYLE_VOICE_MAP.items()}
    for key, voice_id in VOICES.items():
        badge = f"  [dim]→ {style_defaults[key]}[/]" if key in style_defaults else ""
        t.add_row(key, voice_id, f"{notes.get(key, '')}{badge}")
    console.print(Panel(
        t, title=f"[bold {C_ACCENT}]TTS voices[/]", border_style=C_DIM, box=box.ROUNDED,
    ))


@app.command()
def providers() -> None:
    """[dim]List image generation providers and their auth status.[/]"""
    console.print()
    env = {
        "bfl":          ("BFL_API_KEY",          "paid",  "Black Forest Labs Flux 1.1 Pro"),
        "fal":          ("FAL_KEY",               "paid",  "Fal.ai Flux Dev"),
        "prodia":       ("PRODIA_TOKEN",           "paid",  "Prodia Flux Schnell"),
        "pollinations": (None,                     "free",  "Pollinations flux-realism (no key)"),
        "huggingface":  ("HF_TOKEN",              "free",  "HuggingFace FLUX.1-schnell"),
        "stable_horde": ("STABLE_HORDE_API_KEY",  "free",  "community GPU cluster"),
        "together":     ("TOGETHER_API_KEY",       "free",  "Together AI FLUX schnell"),
    }

    t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=True, padding=(0, 2))
    t.add_column("status",   no_wrap=True, width=8)
    t.add_column("provider", style=f"bold {C_ACCENT}", no_wrap=True)
    t.add_column("tier",     no_wrap=True, width=6)
    t.add_column("notes",    style="white")

    for name, (env_var, tier, notes) in env.items():
        if env_var is None:
            status = f"[bold {C_SUCCESS}]ready[/]"
        elif os.environ.get(env_var):
            status = f"[bold {C_SUCCESS}]ready[/]"
        else:
            status = f"[{C_MUTED}]no key[/]"

        tier_fmt = (
            f"[dim {C_SUCCESS}]free[/]" if tier == "free"
            else "[dim yellow]paid[/]"
        )
        t.add_row(status, name, tier_fmt, notes)

    console.print(Panel(
        t,
        title=f"[bold {C_ACCENT}]image providers[/]  [dim](tried in order listed)[/]",
        border_style=C_DIM,
        box=box.ROUNDED,
    ))


@app.command()
def gui() -> None:
    """[dim]Launch the retro desktop control panel.[/]"""
    from .gui import main as gui_main
    gui_main()


# ── auto ──────────────────────────────────────────────────────────────────────

@app.command()
def auto(
    count: int  = typer.Option(3, "--count", "-n", help="Number of Shorts to generate"),
    upload: bool = typer.Option(False, "--upload"),
    privacy: str = typer.Option("public", "--privacy"),
    style: Optional[str] = typer.Option(None, "--style"),
    voice: str  = typer.Option("en-female", "-v", "--voice"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    brand_name: str = typer.Option("", "--brand-name", help="Channel name for thumbnail branding"),
    accent_color: str = typer.Option("#c084ff", "--accent-color", help="Hex color for thumbnail accent bar"),
) -> None:
    """[bold magenta]Auto-pilot: harvest trending topics → generate Shorts → upload.[/]"""
    print_banner()
    if style and style not in _STYLE_CHOICES:
        error(f"unknown style '{style}' — choose from: {', '.join(_STYLE_CHOICES)}")
        raise typer.Exit(1)
    accent_color = _validate_hex_color(accent_color)
    selected_voice = VOICES.get(voice, voice)
    _run_async(_run_auto_async(
        count=count,
        upload=upload,
        privacy=privacy,
        style=style,
        voice=selected_voice,
        quiet=quiet,
        dry_run=dry_run,
        brand_name=brand_name,
        accent_color=accent_color,
    ))


# ── youtube-setup ─────────────────────────────────────────────────────────────

@app.command(name="youtube-setup")
def youtube_setup() -> None:
    """[dim]One-time OAuth2 setup for YouTube auto-upload.[/]"""
    from .auto.youtube import setup_oauth, SECRETS_PATH, TOKEN_PATH

    console.print()
    console.print(Rule(f"[bold {C_ACCENT}]YouTube OAuth2 setup[/]", style=C_DIM))
    console.print()
    info(f"secrets: {SECRETS_PATH}")
    info(f"token:   {TOKEN_PATH}")
    console.print()

    if TOKEN_PATH.exists():
        success("already configured — token file exists")
        info(f"to re-authenticate: rm {TOKEN_PATH}")
        return

    if not SECRETS_PATH.exists():
        warn("client_secrets.json not found\n")
        console.print(
            "  1. console.cloud.google.com → APIs & Services\n"
            "     → Enable [bold]YouTube Data API v3[/]\n"
            "  2. Credentials → Create OAuth 2.0 Client ID → Desktop app\n"
            "  3. Download JSON → save to:\n"
            f"     [cyan]{SECRETS_PATH}[/]\n"
            "  4. Re-run this command"
        )
        raise typer.Exit(1)

    info("opening browser for Google auth…")
    try:
        setup_oauth()
        success("YouTube configured")
    except Exception as e:
        error(str(e))
        raise typer.Exit(1)


# ── channel subcommand group ──────────────────────────────────────────────────

channel_app = typer.Typer(
    name="channel",
    help="Multi-channel automation — manage and run automated YouTube channels.",
    rich_markup_mode="rich",
    add_completion=False,
)
app.add_typer(channel_app, name="channel")


@channel_app.command("list")
def channel_list() -> None:
    """[dim]List all configured channels with their status.[/]"""
    from .channels.config import ChannelConfig
    names = ChannelConfig.list_all()
    if not names:
        info("no channels configured — run: ffmpeg-ai channel init-presets")
        return

    console.print()
    t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=True, padding=(0, 1))
    t.add_column("channel", style=f"bold {C_ACCENT}", no_wrap=True, min_width=10)
    t.add_column("style",   style="yellow",           no_wrap=True, min_width=11)
    t.add_column("voice",   style=C_MUTED,            no_wrap=True, min_width=14)
    t.add_column("upload",  no_wrap=True,             min_width=6)
    t.add_column("yt",      no_wrap=True,             min_width=4)
    t.add_column("src",     style=C_MUTED,            no_wrap=True, min_width=3)

    for name in names:
        try:
            ch = ChannelConfig.load(name)
            upload_fmt = f"[{C_SUCCESS}]on[/]" if ch.upload else f"[{C_MUTED}]off[/]"
            yt_fmt     = f"[{C_SUCCESS}]ok[/]" if ch.is_youtube_configured else f"[{C_MUTED}]–[/]"
            t.add_row(
                ch.name, ch.style, ch.voice,
                upload_fmt, yt_fmt, str(len(ch.sources)),
            )
        except Exception as e:
            t.add_row(name, f"[{C_ERROR}]{e}[/]", "", "", "", "")

    console.print(Panel(
        t, title=f"[bold {C_ACCENT}]channels[/]", border_style=C_DIM, box=box.ROUNDED,
    ))


@channel_app.command("init-presets")
def channel_init_presets(
    force: bool = typer.Option(False, "--force", help="Overwrite existing configs"),
) -> None:
    """[dim]Install all 6 built-in channel presets.[/]"""
    from .channels.config import CHANNELS_DIR, ChannelConfig, PRESETS
    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    console.print()

    for preset in PRESETS:
        path = CHANNELS_DIR / f"{preset['name']}.json"
        if path.exists() and not force:
            info(f"{preset['name']} — skipped (exists, use --force to overwrite)")
            continue
        ChannelConfig(**preset).save()
        success(f"{preset['name']}  ({preset['display_name']})")

    console.print()
    info(f"configs in {CHANNELS_DIR}")
    info("edit JSON files to customise, then run: ffmpeg-ai channel run <name>")


@channel_app.command("run")
def channel_run(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit to run all)"),
    shorts: bool    = typer.Option(True, "--shorts/--no-shorts"),
    landscape: bool = typer.Option(True, "--landscape/--no-landscape"),
    upload: Optional[bool] = typer.Option(None, "--upload/--no-upload"),
    count: int  = typer.Option(1, "--count", "-n", help="Topics per channel"),
    model: str  = typer.Option(FREE_MODELS[0], "-m", "--model"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Harvest only, no generation"),
) -> None:
    """[bold magenta]Run a channel (or all channels): harvest → generate → upload.[/]"""
    if not os.environ.get("OPENROUTER_API_KEY", ""):
        error("OPENROUTER_API_KEY not set")
        raise typer.Exit(1)

    from .channels.config import ChannelConfig

    names = [name] if name else ChannelConfig.list_all()
    if not names:
        info("no channels configured — run: ffmpeg-ai channel init-presets")
        raise typer.Exit(0)

    print_banner()
    _run_async(_run_channels_async(
        channel_names=names,
        shorts=shorts,
        landscape=landscape,
        upload=upload,
        count=count,
        model=model,
        quiet=quiet,
        dry_run=dry_run,
    ))


@channel_app.command("status")
def channel_status(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit for all)"),
    lines: int = typer.Option(5, "--lines", "-n"),
) -> None:
    """[dim]Show recent run history for one or all channels.[/]"""
    from .channels.config import ChannelConfig
    from .channels.runner import read_run_log

    names = [name] if name else ChannelConfig.list_all()
    if not names:
        info("no channels configured")
        return

    for ch_name in names:
        try:
            ch = ChannelConfig.load(ch_name)
        except FileNotFoundError:
            error(f"{ch_name}: not found")
            continue
        entries = read_run_log(ch, limit=lines)
        console.print()
        console.print(Rule(
            f"[bold {C_ACCENT}]{ch.display_name}[/]  [dim]({ch_name})[/]",
            style=C_DIM,
        ))
        if not entries:
            info("no runs yet")
            continue
        t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=True, padding=(0, 2))
        t.add_column("timestamp", style=C_MUTED,           no_wrap=True)
        t.add_column("topics",    style="white")
        t.add_column("videos",    style=f"bold {C_ACCENT}", no_wrap=True, width=7)
        t.add_column("uploaded",  style=f"bold {C_SUCCESS}", no_wrap=True, width=8)
        t.add_column("elapsed",   style=C_MUTED,            no_wrap=True, width=8)
        for e in entries:
            ts      = e.get("timestamp", "")[:16].replace("T", " ")
            topics  = ", ".join(e.get("topics", []))[:55]
            n_gen   = str(len(e.get("generated", [])))
            n_up    = str(len(e.get("uploaded", [])))
            elapsed = f"{e.get('elapsed_s', 0)}s"
            t.add_row(ts, topics, n_gen, n_up, elapsed)
        console.print(t)


@channel_app.command("validate")
def channel_validate(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit for all)"),
) -> None:
    """[dim]Validate channel configs for known errors.[/]"""
    from .channels.config import ChannelConfig
    names = [name] if name else ChannelConfig.list_all()
    console.print()
    all_ok = True
    for ch_name in names:
        try:
            ch = ChannelConfig.load(ch_name)
        except Exception as e:
            error(f"{ch_name}: failed to load — {e}")
            all_ok = False
            continue
        errs = ch.validate()
        if errs:
            all_ok = False
            for e in errs:
                error(f"{ch_name}: {e}")
        else:
            yt = f"  [dim](yt {'ok' if ch.is_youtube_configured else 'not set up'})[/]"
            success(f"{ch_name}{yt}")
    console.print()
    if all_ok:
        success("all configs valid")


@channel_app.command("edit")
def channel_edit(
    name: str = typer.Argument(..., help="Channel name"),
) -> None:
    """[dim]Open a channel's JSON config in $EDITOR.[/]"""
    import shlex
    import subprocess
    from .channels.config import CHANNELS_DIR, ChannelConfig
    path = CHANNELS_DIR / f"{name}.json"
    if not path.exists():
        error(f"channel '{name}' not found")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "nano")
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
    except FileNotFoundError:
        error(f"editor not found: {editor!r} — set $EDITOR")
        raise typer.Exit(1)
    try:
        ch   = ChannelConfig.load(name)
        errs = ch.validate()
        if errs:
            for e in errs:
                warn(e)
        else:
            success(f"{name} saved and valid")
    except Exception as e:
        error(f"config error after edit: {e}")


@channel_app.command("setup-yt")
def channel_setup_yt(
    name: str = typer.Argument(..., help="Channel name"),
) -> None:
    """[dim]Run YouTube OAuth2 for a specific channel.[/]"""
    from .channels.config import ChannelConfig
    from .auto.youtube import setup_oauth

    try:
        ch = ChannelConfig.load(name)
    except FileNotFoundError as e:
        error(str(e))
        raise typer.Exit(1)

    console.print()
    console.print(Rule(
        f"[bold {C_ACCENT}]YouTube OAuth2[/]  [dim]channel: {name}[/]",
        style=C_DIM,
    ))
    console.print()
    info(f"secrets: {ch.secrets_path}")
    info(f"token:   {ch.token_path}")
    console.print()

    if ch.is_youtube_configured:
        success("already configured — token file exists")
        info(f"to re-authenticate: rm {ch.token_path}")
        return

    if not ch.secrets_path.exists():
        warn("client_secrets.json not found\n")
        console.print(
            "  1. console.cloud.google.com → APIs & Services\n"
            "     → Enable [bold]YouTube Data API v3[/]\n"
            "  2. Credentials → Create OAuth 2.0 Client ID → Desktop app\n"
            "  3. Download JSON → save to:\n"
            f"     [cyan]{ch.secrets_path}[/]\n"
            "  4. Re-run this command"
        )
        raise typer.Exit(1)

    info("opening browser for Google auth…")
    try:
        setup_oauth(secrets_path=ch.secrets_path, token_path=ch.token_path)
        success("YouTube configured")
        ch.upload = True
        ch.save()
        info(f"upload=true saved to {ch.name}.json")
    except Exception as e:
        error(str(e))
        raise typer.Exit(1)


@channel_app.command("timer-install")
def channel_timer_install(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit to install all)"),
    hour: int  = typer.Option(9, "--hour", help="Base hour (24h local); channels stagger +3h"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """[dim]Install systemd user timers for automated daily channel runs.[/]"""
    import shutil
    from .channels.config import ChannelConfig

    channels = [name] if name else ChannelConfig.list_all()
    if not channels:
        info("no channels configured — run: ffmpeg-ai channel init-presets")
        return

    import ffmpeg_ai as _pkg
    ffmpeg_ai_bin = shutil.which("ffmpeg-ai") or "ffmpeg-ai"
    # Locate .env relative to the installed package source, fall back to config dir
    _pkg_root = Path(_pkg.__file__).parent.parent.parent
    env_file  = _pkg_root / ".env" if (_pkg_root / ".env").exists() else (
        Path.home() / ".config" / "ffmpeg-ai" / ".env"
    )
    systemd_dir = Path.home() / ".config" / "systemd" / "user"

    console.print()
    if not dry_run:
        console.print(Rule(f"[bold {C_ACCENT}]installing timers[/]", style=C_DIM))
        console.print()

    for i, ch_name in enumerate(channels):
        run_hour     = (hour + i * 3) % 24
        service_name = f"ffmpeg-ai-{ch_name}"

        service_unit = (
            "[Unit]\n"
            f"Description=ffmpeg-ai auto channel: {ch_name}\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={ffmpeg_ai_bin} channel run {ch_name} -q\n"
            f"EnvironmentFile=-{env_file}\n"
            "StandardOutput=journal\n"
            "StandardError=journal\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        timer_unit = (
            "[Unit]\n"
            f"Description=Daily ffmpeg-ai run — channel: {ch_name}\n\n"
            "[Timer]\n"
            f"OnCalendar=*-*-* {run_hour:02d}:00:00\n"
            "AccuracySec=30m\n"
            "Persistent=true\n"
            "RandomizedDelaySec=900\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

        if dry_run:
            console.print(Rule(f"[dim]{service_name}[/]", style=C_DIM))
            console.print(f"[dim]{service_unit}[/]")
            console.print(f"[dim]{timer_unit}[/]")
        else:
            systemd_dir.mkdir(parents=True, exist_ok=True)
            (systemd_dir / f"{service_name}.service").write_text(service_unit)
            (systemd_dir / f"{service_name}.timer").write_text(timer_unit)
            success(f"{service_name}  (daily at {run_hour:02d}:00)")

    if not dry_run:
        console.print()
        console.print(Rule(f"[{C_ACCENT}]enable[/]", style=C_DIM))
        console.print()
        info("systemctl --user daemon-reload")
        for ch_name in channels:
            info(f"systemctl --user enable --now ffmpeg-ai-{ch_name}.timer")


# ── music subcommand group ────────────────────────────────────────────────────

music_app = typer.Typer(
    name="music",
    help="Manage the royalty-free background music cache.",
    rich_markup_mode="rich",
    add_completion=False,
)
app.add_typer(music_app, name="music")


@music_app.command("list")
def music_list() -> None:
    """[dim]Show all cached music tracks per style.[/]"""
    from .auto.music import list_cached, _CACHE_DIR
    cached = list_cached()
    console.print()
    if not cached:
        info("no tracks cached yet — run: ffmpeg-ai music fetch <style>")
        info(f"cache directory: {_CACHE_DIR}")
        return
    t = Table(box=box.SIMPLE, border_style=C_DIM, show_header=True, padding=(0, 2))
    t.add_column("style",  style=f"bold {C_ACCENT}", no_wrap=True, min_width=14)
    t.add_column("tracks", style=C_MUTED,            no_wrap=True, min_width=6)
    t.add_column("files",  style="white")
    for style, files in cached.items():
        t.add_row(style, str(len(files)), ", ".join(files))
    console.print(Panel(
        t, title=f"[bold {C_ACCENT}]music cache[/]", border_style=C_DIM, box=box.ROUNDED,
    ))
    info(f"cache: {_CACHE_DIR}")


@music_app.command("fetch")
def music_fetch(
    style: str = typer.Argument("ambient", help="Style to fetch: ambient/upbeat/dramatic/cinematic/documentary/educational"),  # noqa: E501
    count: int = typer.Option(3, "--count", "-n", help="Minimum tracks to cache"),
) -> None:
    """[dim]Pre-fetch and cache royalty-free tracks for a music style.[/]"""
    from .auto.music import _ensure_cached, _CCMIXTER_TAGS
    valid = list(_CCMIXTER_TAGS)
    if style not in valid:
        error(f"unknown style '{style}' — choose from: {', '.join(valid)}")
        raise typer.Exit(1)
    info(f"fetching {style} tracks (min {count})…")
    tracks = _run_async(_ensure_cached(style, min_tracks=count))
    if tracks:
        success(f"{len(tracks)} track(s) cached for style '{style}'")
        for t in tracks:
            console.print(f"  [dim]{t.name}[/]")
    else:
        warn("no tracks downloaded — check network or try again later")


@music_app.command("add")
def music_add(
    url: str  = typer.Argument(..., help="YouTube / SoundCloud / direct audio URL"),
    style: str = typer.Argument("ambient", help="Style to file it under"),
) -> None:
    """[dim]Download audio from a URL (via yt-dlp) and add it to the music cache.[/]

    Use this to seed the library from the YouTube Audio Library or any
    royalty-free source. Example:

      ffmpeg-ai music add "https://www.youtube.com/watch?v=XXXX" ambient
    """
    from .auto.music import download_from_url, _CCMIXTER_TAGS
    valid = list(_CCMIXTER_TAGS)
    if style not in valid:
        error(f"unknown style '{style}' — choose from: {', '.join(valid)}")
        raise typer.Exit(1)
    info(f"downloading → style: {style}  (via yt-dlp)…")
    path = download_from_url(url, style)
    if path:
        success(f"cached: {path.name}  ({path.stat().st_size // 1024} KB)")
    else:
        error("download failed — check the URL or yt-dlp installation")
        raise typer.Exit(1)


@music_app.command("clear")
def music_clear(
    style: Optional[str] = typer.Argument(None, help="Style to clear (omit for all)"),
) -> None:
    """[dim]Delete cached music tracks.[/]"""
    from .auto.music import clear_cache
    n = clear_cache(style)
    if n:
        success(f"removed {n} track(s)" + (f" for style '{style}'" if style else ""))
    else:
        info("nothing to clear")


if __name__ == "__main__":
    app()
