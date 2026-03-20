"""Rich progress widgets and live pipeline display."""
from contextlib import contextmanager
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TimeElapsedColumn, TaskProgressColumn, MofNCompleteColumn,
)
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

PIPELINE_STAGES = [
    "script",
    "images",
    "tts",
    "captions",
    "compose",
    "export",
]


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots2", style="cyan"),
        TextColumn("[bold white]{task.description}"),
        BarColumn(bar_width=32, style="cyan", complete_style="bright_cyan"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        expand=False,
    )


@contextmanager
def pipeline_progress(title: str = "Generating Short"):
    progress = make_progress()
    with Live(
        Panel(progress, title=f"[bold cyan]{title}[/]", border_style="cyan", box=box.ROUNDED),
        console=console,
        refresh_per_second=12,
    ):
        yield progress


def stats_table(data: dict[str, str]) -> Table:
    """Render a key/value stats panel (e.g. model used, duration, etc.)."""
    t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    t.add_column("key", style="dim cyan", no_wrap=True)
    t.add_column("val", style="white")
    for k, v in data.items():
        t.add_row(k, v)
    return t
