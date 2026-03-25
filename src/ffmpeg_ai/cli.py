"""CLI entry point."""
import asyncio
from pathlib import Path
from typing import Optional
import typer
from dotenv import load_dotenv
from rich.table import Table
from rich.panel import Panel
from rich import box

from .ui.display import print_banner, console
from .ai.openrouter import FREE_MODELS
from .ai.tts import VOICES
from .ai.images import USER_IMAGES_DIR

load_dotenv()
app = typer.Typer(
    name="ffmpeg-ai",
    help="AI-powered YouTube Shorts generator",
    rich_markup_mode="rich",
    invoke_without_command=True,
)


@app.callback()
def main(ctx: typer.Context):
    """AI-powered YouTube Shorts generator."""
    if ctx.invoked_subcommand is not None:
        return

    print_banner()

    # ── subcommands ──────────────────────────────────────────────────────────
    cmd_table = Table(box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2))
    cmd_table.add_column("cmd", style="bold cyan", no_wrap=True)
    cmd_table.add_column("desc", style="white")
    cmd_table.add_row("generate", "generate a YouTube Short from a topic  [dim](main command)[/]")
    cmd_table.add_row("models",   "list available free OpenRouter models")
    cmd_table.add_row("voices",   "list available TTS voices")
    cmd_table.add_row("providers","list image generation providers + auth status")
    console.print(Panel(cmd_table, title="[bold white]commands[/]", border_style="bright_black", box=box.ROUNDED))

    # ── generate arguments ───────────────────────────────────────────────────
    arg_table = Table(box=box.SIMPLE, border_style="bright_black", show_header=True, padding=(0, 2))
    arg_table.add_column("argument",  style="bold cyan",  no_wrap=True)
    arg_table.add_column("type",      style="dim white",  no_wrap=True)
    arg_table.add_column("default",   style="yellow",     no_wrap=True)
    arg_table.add_column("description", style="white")

    arg_table.add_row("TOPIC",          "str",  "(required)", "Topic or idea for the Short")
    arg_table.add_row("-o / --output",  "path", "output/short.mp4", "Output file path")
    arg_table.add_row("-d / --duration","int",  "45",         "Target duration in seconds (max 58)")
    arg_table.add_row("-m / --model",   "str",  "llama-3.3-70b:free", "OpenRouter model ID (see: ffmpeg-ai models)")
    arg_table.add_row("-v / --voice",   "str",  "en-female",  f"TTS voice key: {', '.join(VOICES.keys())}  (see: ffmpeg-ai voices)")
    arg_table.add_row("-M / --music",   "path", "none",       "Background music file (MP3/WAV) — auto-ducked under narration")
    arg_table.add_row("-I / --images-dir","path","none",      "Use images from this directory instead of AI generation")
    arg_table.add_row("--no-ai-images", "flag", "off",        "Disable AI image generation (use PIL placeholders or --images-dir)")
    arg_table.add_row("--providers",    "str",  "pollinations,huggingface", "Comma-separated image provider order")
    arg_table.add_row("--dry-run",      "flag", "off",        "Generate script only — no video rendered")
    console.print(Panel(arg_table, title="[bold white]generate — arguments[/]", border_style="bright_black", box=box.ROUNDED))

    # ── examples ─────────────────────────────────────────────────────────────
    ex_table = Table(box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2))
    ex_table.add_column("label", style="dim white",  no_wrap=True, min_width=20)
    ex_table.add_column("cmd",   style="bold green")

    ex_table.add_row("basic",
        'ffmpeg-ai generate "5 facts about black holes"')
    ex_table.add_row("custom output",
        'ffmpeg-ai generate "stoic morning routine" -o ~/Videos/stoic.mp4')
    ex_table.add_row("longer short",
        'ffmpeg-ai generate "how GPUs work" -d 58')
    ex_table.add_row("different voice",
        'ffmpeg-ai generate "ancient rome" -v en-male')
    ex_table.add_row("different model",
        f'ffmpeg-ai generate "dark matter" -m {FREE_MODELS[2]}')
    ex_table.add_row("add background music",
        'ffmpeg-ai generate "lofi study tips" -M assets/music/lofi.mp3')
    ex_table.add_row("your own images",
        'ffmpeg-ai generate "my travel vlog" -I ~/Pictures/trip/')
    ex_table.add_row("no AI images",
        'ffmpeg-ai generate "test topic" --no-ai-images -o test.mp4')
    ex_table.add_row("huggingface images only",
        'ffmpeg-ai generate "cyberpunk city" --providers huggingface')
    ex_table.add_row("script preview only",
        'ffmpeg-ai generate "mars colonization" --dry-run')
    ex_table.add_row("full custom",
        f'ffmpeg-ai generate "quantum computing" -d 50 -v en-news -m {FREE_MODELS[1]} -o out/quantum.mp4')
    console.print(Panel(ex_table, title="[bold white]examples[/]", border_style="bright_black", box=box.ROUNDED))

    # ── env vars ─────────────────────────────────────────────────────────────
    env_table = Table(box=box.SIMPLE, border_style="bright_black", show_header=False, padding=(0, 2))
    env_table.add_column("var",   style="bold cyan",  no_wrap=True)
    env_table.add_column("desc",  style="white")
    env_table.add_row("OPENROUTER_API_KEY", "required for LLM script generation  [dim](free tier, no credit card)[/]")
    env_table.add_row("HF_TOKEN",           "optional — enables HuggingFace image provider")
    console.print(Panel(env_table, title="[bold white]env vars  (.env supported)[/]", border_style="bright_black", box=box.ROUNDED))


@app.command()
def generate(
    topic: str = typer.Argument(..., help="Topic or idea for the Short"),
    output: Path = typer.Option(Path("output/short.mp4"), "-o", "--output", help="Output file path"),
    duration: int = typer.Option(45, "-d", "--duration", help="Target duration in seconds (max 58)"),
    model: str = typer.Option(FREE_MODELS[0], "-m", "--model", help="OpenRouter model ID"),
    voice: str = typer.Option("en-female", "-v", "--voice", help=f"Voice: {', '.join(VOICES.keys())}"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate script only, no video"),
    images_dir: Optional[Path] = typer.Option(
        None, "--images-dir", "-I",
        help=f"Use images from this directory instead of AI generation. "
             f"Default user folder: {USER_IMAGES_DIR}",
    ),
    no_ai_images: bool = typer.Option(
        False, "--no-ai-images",
        help="Disable AI image generation (use PIL placeholders unless --images-dir is set)",
    ),
    providers: Optional[str] = typer.Option(
        None, "--providers",
        help='Comma-separated AI image provider order. Available: "pollinations,huggingface". '
             'Default: "pollinations,huggingface"',
    ),
    music: Optional[Path] = typer.Option(
        None, "--music", "-M",
        help="Background music file (MP3/WAV). Auto-ducked under narration. "
             "Drop tracks in assets/music/ and pass one here.",
    ),
):
    """[bold cyan]Generate a YouTube Short from a topic.[/]"""
    print_banner()

    # Resolve images_dir
    resolved_images_dir: Optional[Path] = None
    if images_dir is not None:
        if not images_dir.is_dir():
            console.print(f"[bold red]✗[/] --images-dir not found: {images_dir}")
            raise typer.Exit(1)
        resolved_images_dir = images_dir

    if music is not None and not music.is_file():
        console.print(f"[bold red]✗[/] --music file not found: {music}")
        raise typer.Exit(1)

    provider_list = [p.strip() for p in providers.split(",")] if providers else None

    from .pipeline import run_pipeline
    selected_voice = VOICES.get(voice, voice)
    asyncio.run(run_pipeline(
        topic=topic,
        output_path=output,
        duration=min(duration, 58),
        model=model,
        voice=selected_voice,
        dry_run=dry_run,
        images_dir=resolved_images_dir,
        use_ai_images=not no_ai_images,
        image_providers=provider_list,
        music_path=music,
    ))


@app.command()
def models():
    """[dim]List available free OpenRouter models.[/]"""
    from rich.table import Table
    from rich import box
    t = Table(box=box.SIMPLE, border_style="cyan", show_header=True)
    t.add_column("Model", style="cyan")
    for m in FREE_MODELS:
        t.add_row(m)
    console.print(t)


@app.command()
def voices():
    """[dim]List available TTS voices.[/]"""
    from rich.table import Table
    from rich import box
    t = Table(box=box.SIMPLE, border_style="cyan")
    t.add_column("Key", style="cyan")
    t.add_column("Voice ID", style="white")
    for k, v in VOICES.items():
        t.add_row(k, v)
    console.print(t)


@app.command()
def providers():
    """[dim]List available image generation providers.[/]"""
    import os
    from rich.table import Table
    from rich import box
    t = Table(box=box.SIMPLE, border_style="cyan")
    t.add_column("Provider", style="cyan")
    t.add_column("Auth required", style="white")
    t.add_column("Status", style="white")
    hf_key = os.environ.get("HF_TOKEN", "")
    t.add_row("pollinations", "none", "[green]ready[/]")
    t.add_row(
        "huggingface",
        "HF_TOKEN",
        "[green]ready[/]" if hf_key else "[dim]set HF_TOKEN to enable[/]",
    )
    console.print(t)


if __name__ == "__main__":
    app()
