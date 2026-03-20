"""CLI entry point."""
import asyncio
from pathlib import Path
from typing import Optional
import typer
from dotenv import load_dotenv

from .ui.display import print_banner, console
from .ai.openrouter import FREE_MODELS
from .ai.tts import VOICES
from .ai.images import USER_IMAGES_DIR

load_dotenv()
app = typer.Typer(
    name="ffmpeg-ai",
    help="AI-powered YouTube Shorts generator",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


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
