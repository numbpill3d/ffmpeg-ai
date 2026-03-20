"""ASCII banner and pipeline status display."""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align

console = Console()

BANNER = r"""
  ███████╗███████╗███╗   ███╗██████╗ ███████╗ ██████╗      █████╗ ██╗
  ██╔════╝██╔════╝████╗ ████║██╔══██╗██╔════╝██╔════╝     ██╔══██╗██║
  █████╗  █████╗  ██╔████╔██║██████╔╝█████╗  ██║  ███╗   ███████║██║
  ██╔══╝  ██╔══╝  ██║╚██╔╝██║██╔═══╝ ██╔══╝  ██║   ██║   ██╔══██║██║
  ██║     ██║     ██║ ╚═╝ ██║██║     ███████╗╚██████╔╝   ██║  ██║██║
  ╚═╝     ╚═╝     ╚═╝     ╚═╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝  ╚═╝╚═╝
"""

def print_banner():
    text = Text(BANNER, style="bold cyan")
    subtitle = Text("  YouTube Shorts Generator  ·  powered by free AI  ·  ffmpeg\n", style="dim white")
    console.print(Align.center(text))
    console.print(Align.center(subtitle))


def print_stage(stage: str, detail: str = ""):
    label = f"[bold magenta]{stage}[/]"
    if detail:
        label += f"  [dim]{detail}[/]"
    console.print(Panel(label, border_style="bright_black", padding=(0, 2)))


def print_success(msg: str):
    console.print(f"[bold green]✓[/] {msg}")


def print_error(msg: str):
    console.print(f"[bold red]✗[/] {msg}")


def print_info(msg: str):
    console.print(f"[dim cyan]·[/] {msg}")
