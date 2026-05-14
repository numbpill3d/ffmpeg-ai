"""ASCII banner and pipeline status display."""
from rich.console import Console
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
    subtitle = Text(
        "  YouTube Shorts Generator  ·  powered by free AI  ·  ffmpeg\n", style="dim white"
    )
    console.print(Align.center(text))
    console.print(Align.center(subtitle))

