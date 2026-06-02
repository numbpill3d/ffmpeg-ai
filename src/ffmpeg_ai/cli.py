"""CLI entry point."""
import asyncio
import datetime
import os
import re
from pathlib import Path
from typing import Optional
import typer
from dotenv import load_dotenv
from rich.table import Table
from rich.panel import Panel
from rich import box

from .ui.display import print_banner, console
from .ai.openrouter import FREE_MODELS, STYLE_PRESETS
from .ai.tts import VOICES
from .video.shorts import MODES

load_dotenv()
app = typer.Typer(
    name="ffmpeg-ai",
    help="AI-powered YouTube Shorts generator",
    rich_markup_mode="rich",
    invoke_without_command=True,
)

_STYLE_CHOICES = list(STYLE_PRESETS.keys())
_CAPTION_CHOICES = ["karaoke", "plain", "bold-center"]


@app.callback()
def main(ctx: typer.Context):
    """AI-powered YouTube Shorts generator."""
    if ctx.invoked_subcommand is not None:
        return

    print_banner()

    cmd_table = Table(
        box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2)
    )
    cmd_table.add_column("cmd", style="bold cyan", no_wrap=True)
    cmd_table.add_column("desc", style="white")
    cmd_table.add_row("generate",  "generate a YouTube Short from a topic  [dim](main command)[/]")
    cmd_table.add_row("batch",     "generate multiple Shorts from a topics file")
    cmd_table.add_row("models",    "list available free OpenRouter models")
    cmd_table.add_row("voices",    "list available TTS voices")
    cmd_table.add_row("providers", "list image generation providers + auth status")
    console.print(Panel(
        cmd_table, title="[bold white]commands[/]",
        border_style="bright_black", box=box.ROUNDED,
    ))

    arg_table = Table(
        box=box.SIMPLE, border_style="bright_black", show_header=True, padding=(0, 2)
    )
    arg_table.add_column("argument",    style="bold cyan", no_wrap=True)
    arg_table.add_column("type",        style="dim white", no_wrap=True)
    arg_table.add_column("default",     style="yellow",    no_wrap=True)
    arg_table.add_column("description", style="white")

    arg_table.add_row("TOPIC", "str", "(required)", "Topic or idea for the Short")
    arg_table.add_row("-o / --output", "path", "~/Videos/…", "Output file path")
    arg_table.add_row("-d / --duration", "int", "300", "Target duration in seconds (max 600)")
    arg_table.add_row("-m / --model", "str", "llama-3.3-70b:free", "OpenRouter model ID")
    arg_table.add_row("-v / --voice", "str", "en-female", "TTS voice (see: voices command)")
    arg_table.add_row("-M / --music", "path", "none", "Background music (MP3/WAV), auto-ducked")
    arg_table.add_row("-I / --images-dir", "path", "none", "Use images from this directory")
    arg_table.add_row("--script", "path", "none", "Load script JSON (skips LLM)")
    arg_table.add_row("--edit-script", "flag", "off", "Open script in $EDITOR before render")
    arg_table.add_row("--style", "str", "none", f"Tone preset: {', '.join(_STYLE_CHOICES)}")
    arg_table.add_row("--caption-style", "str", "karaoke", ", ".join(_CAPTION_CHOICES))
    arg_table.add_row("--providers", "str", "all", "Image provider order (comma-separated)")
    arg_table.add_row("--no-ai-images", "flag", "off", "Disable AI image generation")
    arg_table.add_row("--thumbnail/--no-thumbnail", "flag", "on", "Extract thumbnail JPEG")
    arg_table.add_row("--no-captions", "flag", "off", "Skip whisper + caption burn")
    arg_table.add_row("--no-ambience", "flag", "off", "Skip background ambience layer")
    arg_table.add_row("--fresh", "flag", "off", "Ignore cache, start from scratch")
    arg_table.add_row("-q / --quiet", "flag", "off", "Minimal output — one line per stage")
    arg_table.add_row("--dry-run", "flag", "off", "Script only, no video rendered")
    console.print(Panel(
        arg_table, title="[bold white]generate — arguments[/]",
        border_style="bright_black", box=box.ROUNDED,
    ))

    ex_table = Table(
        box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2)
    )
    ex_table.add_column("label", style="dim white",  no_wrap=True, min_width=22)
    ex_table.add_column("cmd",   style="bold green")

    ex_table.add_row("basic", 'ffmpeg-ai generate "5 facts about black holes"')
    ex_table.add_row("dramatic style", 'ffmpeg-ai generate "deep sea creatures" --style dramatic')
    ex_table.add_row("listicle", 'ffmpeg-ai generate "productivity hacks" --style listicle')
    ex_table.add_row("edit before render", 'ffmpeg-ai generate "mars colonization" --edit-script')
    ex_table.add_row("resume job", 'ffmpeg-ai generate "ancient rome"  [dim](re-uses cache)[/]')
    ex_table.add_row("fresh run", 'ffmpeg-ai generate "ancient rome" --fresh')
    ex_table.add_row("load saved script", 'ffmpeg-ai generate "topic" --script ~/.cache/…/script.json')  # noqa: E501
    ex_table.add_row("plain captions", 'ffmpeg-ai generate "stoic tips" --caption-style plain')
    ex_table.add_row("no thumbnail", 'ffmpeg-ai generate "test" --no-thumbnail -o test.mp4')
    ex_table.add_row("quiet / batch", 'ffmpeg-ai generate "quantum computing" -q -o out/q.mp4')
    ex_table.add_row("batch", 'ffmpeg-ai batch topics.txt -o ~/Videos/batch/')
    console.print(Panel(
        ex_table, title="[bold white]examples[/]",
        border_style="bright_black", box=box.ROUNDED,
    ))

    env_table = Table(
        box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2)
    )
    env_table.add_column("var",  style="bold cyan", no_wrap=True)
    env_table.add_column("desc", style="white")
    env_table.add_row("OPENROUTER_API_KEY", "required — LLM script generation [dim](free tier)[/]")
    env_table.add_row("BFL_API_KEY", "optional — Black Forest Labs [dim](paid)[/]")
    env_table.add_row("FAL_KEY", "optional — Fal.ai [dim](paid)[/]")
    env_table.add_row("PRODIA_TOKEN", "optional — Prodia [dim](paid)[/]")
    env_table.add_row("HF_TOKEN", "optional — HuggingFace [dim](free)[/]")
    env_table.add_row("STABLE_HORDE_API_KEY", "optional — community GPU cluster [dim](free)[/]")
    env_table.add_row("TOGETHER_API_KEY", "optional — Together AI FLUX schnell [dim](free)[/]")
    env_table.add_row("EDITOR", "editor for --edit-script [dim](default: nano)[/]")
    console.print(Panel(
        env_table, title="[bold white]env vars  (.env supported)[/]",
        border_style="bright_black", box=box.ROUNDED,
    ))


@app.command()
def generate(
    topic: str = typer.Argument(..., help="Topic or idea for the Short"),
    mode: str = typer.Option("shorts", help="Output mode: shorts (9:16) or landscape (16:9)"),
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
    duration: Optional[int] = typer.Option(None, "-d", "--duration", help="Target duration in seconds (max 600; defaults 600 for landscape, 45 for shorts)"),  # noqa: E501
    model: str = typer.Option(FREE_MODELS[0], "-m", "--model"),
    voice: str = typer.Option("en-female", "-v", "--voice"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    images_dir: Optional[Path] = typer.Option(None, "--images-dir", "-I"),
    no_ai_images: bool = typer.Option(False, "--no-ai-images"),
    providers: Optional[str] = typer.Option(None, "--providers"),
    music: Optional[Path] = typer.Option(None, "--music", "-M"),
    script: Optional[Path] = typer.Option(
        None, "--script", help="Load script JSON from file (skips LLM)"
    ),
    edit_script: bool = typer.Option(
        False, "--edit-script", help="Open script in $EDITOR before rendering"
    ),
    fresh: bool = typer.Option(
        False, "--fresh", help="Ignore cached job data and start from scratch"
    ),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Minimal output"),
    no_thumbnail: bool = typer.Option(False, "--no-thumbnail", help="Skip thumbnail extraction"),
    style: Optional[str] = typer.Option(
        None, "--style", help=f"Tone preset: {', '.join(_STYLE_CHOICES)}"
    ),
    caption_style: str = typer.Option(
        "karaoke", "--caption-style", help=f"Caption style: {', '.join(_CAPTION_CHOICES)}"
    ),
    no_captions: bool = typer.Option(
        False, "--no-captions", help="Skip transcription and caption burning"
    ),
    no_ambience: bool = typer.Option(
        False, "--no-ambience", help="Skip background ambience layer"
    ),
):
    """[bold cyan]Generate a YouTube Short from a topic.[/]"""
    print_banner()

    if not os.environ.get("OPENROUTER_API_KEY", "") and script is None:
        console.print("[bold red]error:[/] OPENROUTER_API_KEY not set — add to .env or export it")
        raise typer.Exit(1)

    if mode not in MODES:
        console.print(
            f"[bold red]error:[/] unknown mode '{mode}'. choices: {', '.join(MODES)}"
        )
        raise typer.Exit(1)

    if duration is None:
        duration = 600 if mode == "landscape" else 45

    if style and style not in _STYLE_CHOICES:
        console.print(
            f"[bold red]error:[/] unknown style '{style}'. choices: {', '.join(_STYLE_CHOICES)}"
        )
        raise typer.Exit(1)

    if caption_style not in _CAPTION_CHOICES:
        console.print(
            f"[bold red]error:[/] unknown caption-style '{caption_style}'."
            f" choices: {', '.join(_CAPTION_CHOICES)}"
        )
        raise typer.Exit(1)

    if images_dir is not None and not images_dir.is_dir():
        console.print(f"[bold red]✗[/] --images-dir not found: {images_dir}")
        raise typer.Exit(1)

    if script is not None and not script.is_file():
        console.print(f"[bold red]✗[/] --script file not found: {script}")
        raise typer.Exit(1)

    if music is not None and not music.is_file():
        console.print(f"[bold red]✗[/] --music file not found: {music}")
        raise typer.Exit(1)

    if output is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path.home() / "Videos" / "ffmpeg-ai" / f"{ts}.mp4"

    provider_list = [p.strip() for p in providers.split(",")] if providers else None

    from .pipeline import run_pipeline
    selected_voice = VOICES.get(voice, voice)
    asyncio.run(run_pipeline(
        topic=topic,
        mode=mode,
        output_path=output,
        duration=min(duration, 600),
        model=model,
        voice=selected_voice,
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
        no_captions=no_captions,
        no_ambience=no_ambience,
    ))


@app.command()
def batch(
    topics_file: Path = typer.Argument(
        ..., help="Text file with one topic per line (# lines are comments)"
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "-o", "--output-dir", help="Output directory (default: ~/Videos/ffmpeg-ai/)"
    ),
    mode: str = typer.Option("shorts", help="Output mode: shorts (9:16) or landscape (16:9)"),
    duration: Optional[int] = typer.Option(None, "-d", "--duration", help="Target duration in seconds (max 600; defaults 600 for landscape, 45 for shorts)"),  # noqa: E501
    model: str = typer.Option(FREE_MODELS[0], "-m", "--model"),
    voice: str = typer.Option("en-female", "-v", "--voice"),
    style: Optional[str] = typer.Option(None, "--style"),
    caption_style: str = typer.Option("karaoke", "--caption-style"),
    no_thumbnail: bool = typer.Option(False, "--no-thumbnail"),
    no_ambience: bool = typer.Option(False, "--no-ambience"),
    fresh: bool = typer.Option(False, "--fresh"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """[bold cyan]Generate multiple Shorts from a file of topics (one per line).[/]"""
    if not os.environ.get("OPENROUTER_API_KEY", ""):
        console.print("[bold red]error:[/] OPENROUTER_API_KEY not set")
        raise typer.Exit(1)

    if mode not in MODES:
        console.print(
            f"[bold red]error:[/] unknown mode '{mode}'. choices: {', '.join(MODES)}"
        )
        raise typer.Exit(1)

    if duration is None:
        duration = 600 if mode == "landscape" else 45

    if not topics_file.is_file():
        console.print(f"[bold red]✗[/] file not found: {topics_file}")
        raise typer.Exit(1)

    topics = [
        line.strip()
        for line in topics_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not topics:
        console.print("[bold red]✗[/] no topics found in file")
        raise typer.Exit(1)

    out_dir = output_dir or (Path.home() / "Videos" / "ffmpeg-ai")
    out_dir.mkdir(parents=True, exist_ok=True)

    from .pipeline import run_pipeline
    selected_voice = VOICES.get(voice, voice)

    console.print(f"[bold cyan]batch:[/] {len(topics)} topics → {out_dir}")

    failed = 0
    for i, topic in enumerate(topics, 1):
        console.print(f"\n[bold cyan]── {i}/{len(topics)}: {topic} ──[/]")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")
        out = out_dir / f"{ts}_{slug}.mp4"
        try:
            asyncio.run(run_pipeline(
                topic=topic,
                output_path=out,
                mode=mode,
                duration=min(duration, 600),
                model=model,
                voice=selected_voice,
                style=style,
                caption_style=caption_style,
                thumbnail=not no_thumbnail,
                no_ambience=no_ambience,
                fresh=fresh,
                quiet=quiet,
            ))
        except Exception as e:
            console.print(f"[bold red]✗[/] topic {i} failed: {e}")
            failed += 1
            continue

    status = "[bold green]done[/]" if failed == 0 else f"[bold yellow]done ({failed} failed)[/]"
    console.print(f"\n{status} — {len(topics)} topics processed")


@app.command()
def models():
    """[dim]List available free OpenRouter models.[/]"""
    t = Table(box=box.SIMPLE, border_style="cyan", show_header=True)
    t.add_column("Model", style="cyan")
    for m in FREE_MODELS:
        t.add_row(m)
    console.print(t)


@app.command()
def voices():
    """[dim]List available TTS voices.[/]"""
    t = Table(box=box.SIMPLE, border_style="cyan")
    t.add_column("Key",      style="cyan")
    t.add_column("Voice ID", style="white")
    for k, v in VOICES.items():
        t.add_row(k, v)
    console.print(t)


@app.command()
def providers():
    """[dim]List available image generation providers.[/]"""
    t = Table(box=box.SIMPLE, border_style="cyan")
    t.add_column("Provider",      style="cyan")
    t.add_column("Auth required", style="white")
    t.add_column("Status",        style="white")

    bfl_key    = os.environ.get("BFL_API_KEY", "")
    fal_key    = os.environ.get("FAL_KEY", "")
    prodia_key = os.environ.get("PRODIA_TOKEN", "")
    hf_key     = os.environ.get("HF_TOKEN", "")
    horde_key  = os.environ.get("STABLE_HORDE_API_KEY", "")
    together_key = os.environ.get("TOGETHER_API_KEY", "")

    def _status(key: str) -> str:
        return "[green]ready[/]" if key else "[dim]key not set[/]"

    t.add_row("bfl",          "BFL_API_KEY",         _status(bfl_key))
    t.add_row("fal",          "FAL_KEY",             _status(fal_key))
    t.add_row("prodia",       "PRODIA_TOKEN",         _status(prodia_key))
    t.add_row("pollinations", "none",                 "[green]ready[/]")
    t.add_row("huggingface",  "HF_TOKEN",             _status(hf_key))
    t.add_row(
        "stable_horde",
        "STABLE_HORDE_API_KEY",
        "[green]ready (registered)[/]" if horde_key else "[green]ready (guest)[/]",
    )
    t.add_row("together",     "TOGETHER_API_KEY",     _status(together_key))
    console.print(t)


@app.command()
def auto(
    count: int = typer.Option(3, "--count", "-n", help="Number of Shorts to generate"),
    upload: bool = typer.Option(False, "--upload", help="Upload to YouTube after rendering"),
    privacy: str = typer.Option("public", "--privacy", help="public / unlisted / private"),
    style: Optional[str] = typer.Option(None, "--style"),
    voice: str = typer.Option("en-female", "-v", "--voice"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Harvest topics only, no generation"),
):
    """[bold cyan]Auto-pilot: harvest trending topics → generate Shorts → upload.[/]"""
    import json as _json
    from .auto.harvest import harvest, save_seen
    from .auto.youtube import upload_video, is_configured

    print_banner()
    console.print(f"[bold cyan]harvesting {count} topics…[/]")

    topics = asyncio.run(harvest(count=count))
    if not topics:
        console.print("[bold red]no topics found — try again later[/]")
        raise typer.Exit(1)

    console.print("[green]topics selected:[/]")
    for t in topics:
        console.print(f"  • {t}")

    if dry_run:
        return

    save_seen(topics)

    out_dir = Path.home() / "Videos" / "ffmpeg-ai" / "auto"
    out_dir.mkdir(parents=True, exist_ok=True)

    from .pipeline import run_pipeline
    selected_voice = VOICES.get(voice, voice)

    generated: list[tuple[str, Path]] = []
    for i, topic in enumerate(topics, 1):
        console.print(f"\n[bold cyan]── {i}/{len(topics)}: {topic} ──[/]")
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:32].strip("-")
        out  = out_dir / f"{ts}_{slug}.mp4"
        try:
            asyncio.run(run_pipeline(
                topic=topic, output_path=out, mode="shorts", duration=45,
                voice=selected_voice, style=style, quiet=quiet, thumbnail=True,
            ))
            generated.append((topic, out))
        except Exception as e:
            console.print(f"[bold red]✗[/] {e}")

    if not upload:
        console.print(f"\n[bold green]done[/] — {len(generated)} Shorts in {out_dir}")
        console.print("[dim]add --upload to auto-publish to YouTube[/]")
        return

    if not is_configured():
        console.print(
            "[bold yellow]YouTube not configured — run:[/] "
            "[bold]ffmpeg-ai youtube-setup[/]"
        )
        return

    _JOB_CACHE = Path.home() / ".cache" / "ffmpeg-ai" / "jobs"
    uploaded = 0
    for topic, out in generated:
        job_slug  = re.sub(r"[^a-z0-9-]+", "-", topic.lower().strip())[:48].strip("-") or "untitled"
        script_p  = _JOB_CACHE / job_slug / "script.json"
        script    = _json.loads(script_p.read_text()) if script_p.exists() else {}
        viral     = script.get("viral_package", {})

        title = script.get("title") or topic
        desc  = viral.get("description") or f"{topic} #shorts"
        tags  = viral.get("hashtags") or ["#shorts", "#tech"]
        thumb = out.with_suffix(".thumb.jpg")

        console.print(f"[cyan]uploading:[/] {title}")
        try:
            url = upload_video(
                video_path=out, title=title, description=desc, tags=tags,
                thumbnail_path=thumb if thumb.exists() else None,
                privacy=privacy,
            )
            console.print(f"[bold green]✓[/] {url}")
            uploaded += 1
        except Exception as e:
            console.print(f"[bold red]✗[/] upload failed: {e}")

    console.print(f"\n[bold green]done[/] — {uploaded}/{len(generated)} uploaded")


@app.command(name="youtube-setup")
def youtube_setup():
    """[dim]One-time OAuth2 setup for YouTube auto-upload.[/]"""
    from .auto.youtube import setup_oauth, SECRETS_PATH, TOKEN_PATH
    console.print("[bold cyan]YouTube OAuth2 setup[/]")
    console.print()
    console.print(f"  secrets file: [cyan]{SECRETS_PATH}[/]")
    console.print(f"  token file:   [cyan]{TOKEN_PATH}[/]")
    console.print()
    if TOKEN_PATH.exists():
        console.print("[green]already configured[/] — token file exists")
        console.print("[dim]delete it to re-authenticate[/]")
        return
    if not SECRETS_PATH.exists():
        console.print(
            "[bold yellow]client_secrets.json not found.[/]\n\n"
            "  1. console.cloud.google.com → APIs & Services\n"
            "     → Enable [bold]YouTube Data API v3[/]\n"
            "  2. Credentials → Create OAuth 2.0 Client ID → Desktop app\n"
            "  3. Download JSON → save to:\n"
            f"     [cyan]{SECRETS_PATH}[/]\n"
            "  4. Re-run this command"
        )
        raise typer.Exit(1)
    console.print("opening browser for Google auth…")
    try:
        setup_oauth()
        console.print("[bold green]✓ YouTube configured[/]")
    except Exception as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(1)


channel_app = typer.Typer(
    name="channel",
    help="Multi-channel automation — manage and run automated YouTube channels.",
    rich_markup_mode="rich",
)
app.add_typer(channel_app, name="channel")


# ── channel list ──────────────────────────────────────────────────────────────

@channel_app.command("list")
def channel_list():
    """[dim]List all configured channels with their status.[/]"""
    from .channels.config import ChannelConfig
    names = ChannelConfig.list_all()
    if not names:
        console.print("[dim]no channels configured — run: ffmpeg-ai channel init-presets[/]")
        return
    t = Table(box=box.SIMPLE, border_style="cyan", show_header=True)
    t.add_column("name",     style="cyan",      no_wrap=True)
    t.add_column("display",  style="white",     no_wrap=True)
    t.add_column("style",    style="yellow",    no_wrap=True)
    t.add_column("voice",    style="dim white", no_wrap=True)
    t.add_column("upload",   style="dim white", no_wrap=True)
    t.add_column("yt",       style="dim white", no_wrap=True)
    t.add_column("sources",  style="dim white", no_wrap=True)
    for name in names:
        try:
            ch = ChannelConfig.load(name)
            yt_ok = "[green]ok[/]" if ch.is_youtube_configured else "[dim]—[/]"
            t.add_row(
                ch.name, ch.display_name, ch.style, ch.voice,
                "[green]on[/]" if ch.upload else "[dim]off[/]",
                yt_ok, str(len(ch.sources)),
            )
        except Exception as e:
            t.add_row(name, f"[red]{e}[/]", "", "", "", "", "")
    console.print(t)


# ── channel init-presets ──────────────────────────────────────────────────────

@channel_app.command("init-presets")
def channel_init_presets(
    force: bool = typer.Option(False, "--force", help="Overwrite existing configs"),
):
    """[dim]Install all 6 built-in channel presets.[/]"""
    from .channels.config import CHANNELS_DIR, ChannelConfig, PRESETS
    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    for preset in PRESETS:
        path = CHANNELS_DIR / f"{preset['name']}.json"
        if path.exists() and not force:
            console.print(f"[dim]skip[/] {preset['name']} (exists — use --force to overwrite)")
            continue
        ChannelConfig(**preset).save()
        console.print(f"[bold green]✓[/] {preset['name']}  ({preset['display_name']})")
    console.print(f"\n[dim]configs in {CHANNELS_DIR}[/]")
    console.print("[dim]edit JSON files to customise, then run:[/]")
    console.print("[bold]  ffmpeg-ai channel run <name>[/]")


# ── channel run ───────────────────────────────────────────────────────────────

@channel_app.command("run")
def channel_run(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit to run all)"),
    shorts: bool    = typer.Option(True,  "--shorts/--no-shorts",   help="Generate a Short"),
    landscape: bool = typer.Option(True,  "--landscape/--no-landscape", help="Generate long-form"),
    upload: Optional[bool] = typer.Option(None, "--upload/--no-upload", help="Override upload"),
    count: int   = typer.Option(1, "--count", "-n", help="Topics per channel"),
    model: str   = typer.Option(FREE_MODELS[0], "-m", "--model"),
    quiet: bool  = typer.Option(False, "-q", "--quiet"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Harvest topics only, no generation"),
):
    """[bold cyan]Run a channel (or all channels): harvest → generate → upload.[/]"""
    if not os.environ.get("OPENROUTER_API_KEY", ""):
        console.print("[bold red]error:[/] OPENROUTER_API_KEY not set")
        raise typer.Exit(1)

    from .channels.config import ChannelConfig
    from .channels.runner import run_channel

    if name:
        names = [name]
    else:
        names = ChannelConfig.list_all()
        if not names:
            console.print("[dim]no channels configured — run: ffmpeg-ai channel init-presets[/]")
            raise typer.Exit(0)

    print_banner()
    for ch_name in names:
        try:
            ch = ChannelConfig.load(ch_name)
        except FileNotFoundError as e:
            console.print(f"[bold red]error:[/] {e}")
            continue
        errors = ch.validate()
        if errors:
            for err in errors:
                console.print(f"[bold red]config error ({ch_name}):[/] {err}")
            continue
        asyncio.run(run_channel(
            channel=ch,
            shorts=shorts,
            landscape=landscape,
            upload=upload,
            count=count,
            quiet=quiet,
            model=model,
            dry_run=dry_run,
        ))


# ── channel status ────────────────────────────────────────────────────────────

@channel_app.command("status")
def channel_status(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit for all)"),
    lines: int = typer.Option(5, "--lines", "-n", help="Entries to show per channel"),
):
    """[dim]Show recent run history for one or all channels.[/]"""
    from .channels.config import ChannelConfig
    from .channels.runner import read_run_log

    names = [name] if name else ChannelConfig.list_all()
    if not names:
        console.print("[dim]no channels configured[/]")
        return

    for ch_name in names:
        try:
            ch = ChannelConfig.load(ch_name)
        except FileNotFoundError:
            console.print(f"[red]{ch_name}: not found[/]")
            continue
        entries = read_run_log(ch, limit=lines)
        console.print(f"\n[bold cyan]{ch.display_name}[/]  [dim]({ch_name})[/]")
        if not entries:
            console.print("  [dim]no runs yet[/]")
            continue
        t = Table(box=box.SIMPLE, border_style="bright_black", show_header=True, padding=(0, 1))
        t.add_column("timestamp", style="dim white", no_wrap=True)
        t.add_column("topics",    style="white")
        t.add_column("videos",    style="cyan",      no_wrap=True)
        t.add_column("uploaded",  style="green",     no_wrap=True)
        t.add_column("elapsed",   style="dim white", no_wrap=True)
        for e in entries:
            ts       = e.get("timestamp", "")[:16].replace("T", " ")
            topics   = ", ".join(e.get("topics", []))[:60]
            n_gen    = str(len(e.get("generated", [])))
            n_up     = str(len(e.get("uploaded", [])))
            elapsed  = f"{e.get('elapsed_s', 0)}s"
            t.add_row(ts, topics, n_gen, n_up, elapsed)
        console.print(t)


# ── channel validate ──────────────────────────────────────────────────────────

@channel_app.command("validate")
def channel_validate(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit for all)"),
):
    """[dim]Validate channel configs for known errors.[/]"""
    from .channels.config import ChannelConfig
    names = [name] if name else ChannelConfig.list_all()
    all_ok = True
    for ch_name in names:
        try:
            ch = ChannelConfig.load(ch_name)
        except Exception as e:
            console.print(f"[red]✗[/] {ch_name}: failed to load — {e}")
            all_ok = False
            continue
        errors = ch.validate()
        if errors:
            all_ok = False
            for err in errors:
                console.print(f"[red]✗[/] {ch_name}: {err}")
        else:
            yt = "[green](yt ok)[/]" if ch.is_youtube_configured else "[dim](yt not set up)[/]"
            console.print(f"[green]✓[/] {ch_name}  {yt}")
    if all_ok:
        console.print("[bold green]all configs valid[/]")


# ── channel edit ──────────────────────────────────────────────────────────────

@channel_app.command("edit")
def channel_edit(
    name: str = typer.Argument(..., help="Channel name"),
):
    """[dim]Open a channel's JSON config in $EDITOR.[/]"""
    import shlex
    import subprocess
    from .channels.config import CHANNELS_DIR, ChannelConfig
    path = CHANNELS_DIR / f"{name}.json"
    if not path.exists():
        console.print(f"[bold red]error:[/] channel '{name}' not found")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "nano")
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
    except FileNotFoundError:
        console.print(f"[bold red]error:[/] editor not found: {editor!r} — set $EDITOR")
        raise typer.Exit(1)
    # Validate after edit
    try:
        ch = ChannelConfig.load(name)
        errors = ch.validate()
        if errors:
            for err in errors:
                console.print(f"[bold yellow]warning:[/] {err}")
        else:
            console.print(f"[bold green]✓[/] {name} saved and valid")
    except Exception as e:
        console.print(f"[bold red]config error after edit:[/] {e}")


# ── channel setup-yt ──────────────────────────────────────────────────────────

@channel_app.command("setup-yt")
def channel_setup_yt(
    name: str = typer.Argument(..., help="Channel name"),
):
    """[dim]Run YouTube OAuth2 for a specific channel.[/]"""
    from .channels.config import ChannelConfig
    from .auto.youtube import setup_oauth

    try:
        ch = ChannelConfig.load(name)
    except FileNotFoundError as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(1)

    console.print(f"[bold cyan]YouTube OAuth2 setup — channel: {name}[/]")
    console.print(f"  secrets: [cyan]{ch.secrets_path}[/]")
    console.print(f"  token:   [cyan]{ch.token_path}[/]")
    console.print()

    if ch.is_youtube_configured:
        console.print("[green]already configured[/] — token file exists")
        console.print("[dim]delete it to re-authenticate:[/]")
        console.print(f"[dim]  rm {ch.token_path}[/]")
        return

    if not ch.secrets_path.exists():
        console.print(
            "[bold yellow]client_secrets.json not found.[/]\n\n"
            "  1. console.cloud.google.com → APIs & Services\n"
            "     → Enable [bold]YouTube Data API v3[/]\n"
            "  2. Credentials → Create OAuth 2.0 Client ID → Desktop app\n"
            "  3. Download JSON → save to:\n"
            f"     [cyan]{ch.secrets_path}[/]\n"
            "  4. Re-run this command"
        )
        raise typer.Exit(1)

    console.print("opening browser for Google auth…")
    try:
        setup_oauth(secrets_path=ch.secrets_path, token_path=ch.token_path)
        console.print("[bold green]✓ YouTube configured[/]")
        ch.upload = True
        ch.save()
        console.print(f"[dim]upload=true saved to {ch.name}.json[/]")
    except Exception as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(1)


# ── channel timer-install ─────────────────────────────────────────────────────

@channel_app.command("timer-install")
def channel_timer_install(
    name: Optional[str] = typer.Argument(None, help="Channel name (omit to install all)"),
    hour: int  = typer.Option(9, "--hour", help="Base hour (24h local); channels stagger +3h each"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print units without writing files"),
):
    """[dim]Install systemd user timers for automated daily channel runs.[/]"""
    import shutil
    from .channels.config import ChannelConfig

    channels = [name] if name else ChannelConfig.list_all()
    if not channels:
        console.print("[dim]no channels configured — run: ffmpeg-ai channel init-presets[/]")
        return

    ffmpeg_ai_bin = shutil.which("ffmpeg-ai") or "ffmpeg-ai"
    env_file      = Path.home() / "Projects" / "Software" / "ffmpeg-ai" / ".env"
    systemd_dir   = Path.home() / ".config" / "systemd" / "user"

    for i, ch_name in enumerate(channels):
        run_hour     = (hour + i * 3) % 24
        service_name = f"ffmpeg-ai-{ch_name}"

        # ExecStart written as a single line; no line continuation needed.
        service_unit = (
            "[Unit]\n"
            f"Description=ffmpeg-ai auto channel: {ch_name}\n"
            "After=network-online.target\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={ffmpeg_ai_bin} channel run {ch_name} -q\n"
            f"EnvironmentFile=-{env_file}\n"
            "StandardOutput=journal\n"
            "StandardError=journal\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        timer_unit = (
            "[Unit]\n"
            f"Description=Daily ffmpeg-ai run — channel: {ch_name}\n"
            "\n"
            "[Timer]\n"
            f"OnCalendar=*-*-* {run_hour:02d}:00:00\n"
            "AccuracySec=30m\n"
            "Persistent=true\n"
            "RandomizedDelaySec=900\n"
            "\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

        if dry_run:
            console.print(f"\n[bold cyan]── {service_name}.service ──[/]")
            console.print(service_unit)
            console.print(f"[bold cyan]── {service_name}.timer ──[/]")
            console.print(timer_unit)
        else:
            systemd_dir.mkdir(parents=True, exist_ok=True)
            (systemd_dir / f"{service_name}.service").write_text(service_unit)
            (systemd_dir / f"{service_name}.timer").write_text(timer_unit)
            console.print(f"[bold green]✓[/] {service_name}  (daily at {run_hour:02d}:00)")

    if not dry_run:
        console.print(
            "\n[dim]enable with:[/]\n"
            "  [bold]systemctl --user daemon-reload[/]\n"
            + "\n".join(
                f"  [bold]systemctl --user enable --now ffmpeg-ai-{n}.timer[/]"
                for n in channels
            )
        )


if __name__ == "__main__":
    app()
