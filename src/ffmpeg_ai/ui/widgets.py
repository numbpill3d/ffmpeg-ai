"""Rich live pipeline display and stats widgets."""
import time
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

PENDING = "pending"
RUNNING = "running"
CACHED  = "cached"
DONE    = "done"
FAILED  = "failed"

_ICON = {
    PENDING: "[dim]·[/]",
    RUNNING: "[bold cyan]↺[/]",
    CACHED:  "[bold blue]◉[/]",
    DONE:    "[bold green]✓[/]",
    FAILED:  "[bold red]✗[/]",
}

_ROW_STYLE = {
    PENDING: "dim",
    RUNNING: "white",
    CACHED:  "blue",
    DONE:    "green",
    FAILED:  "red",
}


@dataclass
class _Stage:
    name: str
    status: str = PENDING
    detail: str = ""
    elapsed: float = 0.0
    progress: Optional[tuple[int, int]] = None
    _start: Optional[float] = field(default=None, repr=False)

    def tick(self):
        if self._start and self.status == RUNNING:
            self.elapsed = time.time() - self._start


class PipelineTracker:
    """Context manager that renders a persistent live-updating stage table."""

    def __init__(self, stage_names: list[str], quiet: bool = False):
        self._order = stage_names
        self._stages: dict[str, _Stage] = {n: _Stage(n) for n in stage_names}
        self._quiet = quiet
        self._live: Optional[Live] = None
        self._img_slots: list[str] = []

    def __enter__(self):
        if not self._quiet:
            self._live = Live(
                self._render(),
                console=console,
                refresh_per_second=10,
                transient=False,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *args):
        if self._live:
            self._live.update(self._render())
            self._live.__exit__(*args)

    # ── stage control ─────────────────────────────────────────────────────────

    def start(self, name: str, detail: str = ""):
        s = self._stages[name]
        s.status = RUNNING
        s.detail = detail
        s._start = time.time()
        s.elapsed = 0.0
        self._refresh()

    def update(self, name: str, current: int, total: int, detail: str = ""):
        s = self._stages[name]
        s.progress = (current, total)
        s.tick()
        if detail:
            s.detail = detail
        self._refresh()

    def complete(self, name: str, detail: str = "", cached: bool = False):
        s = self._stages[name]
        s.status = CACHED if cached else DONE
        if detail:
            s.detail = detail
        s.tick()
        s.progress = None
        self._refresh()
        if self._quiet:
            icon = "◉" if cached else "✓"
            t = f"  {s.elapsed:.1f}s" if s.elapsed else ""
            print(f"  {icon}  {name:<12}{t}  {s.detail}")

    def fail(self, name: str, detail: str = ""):
        s = self._stages[name]
        s.status = FAILED
        if detail:
            s.detail = detail
        s.tick()
        self._refresh()
        if self._quiet:
            print(f"  ✗  {name:<12}  {s.detail}")

    def print(self, renderable):
        """Print a renderable inside the live context (appears above the table)."""
        if self._live:
            self._live.console.print(renderable)
        elif not self._quiet:
            console.print(renderable)

    # ── per-image grid ────────────────────────────────────────────────────────

    def set_image_count(self, n: int):
        self._img_slots = ["pending"] * n

    def image_done(self, idx: int, is_placeholder: bool):
        if idx < len(self._img_slots):
            self._img_slots[idx] = "placeholder" if is_placeholder else "done"
        self._refresh()

    # ── internals ────────────────────────────────────────────────────────────

    def _refresh(self):
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Panel:
        t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
        t.add_column("icon",  width=3,  no_wrap=True)
        t.add_column("name",  width=12, no_wrap=True)
        t.add_column("time",  width=7,  no_wrap=True, style="dim")
        t.add_column("detail")

        for name in self._order:
            s = self._stages[name]
            s.tick()
            icon   = _ICON[s.status]
            style  = _ROW_STYLE[s.status]
            t_str  = f"{s.elapsed:.1f}s" if s.elapsed > 0 else "–"
            detail = s.detail

            if s.progress is not None:
                cur, tot = s.progress
                w      = 16
                filled = int(w * cur / max(tot, 1))
                bar    = f"[cyan]{'█' * filled}{'░' * (w - filled)}[/]"
                detail = f"{bar}  {cur}/{tot}  {detail}"

            if name == "IMAGES" and self._img_slots:
                grid = "".join(
                    "[green]▪[/]"  if x == "done"
                    else "[yellow]▫[/]" if x == "placeholder"
                    else "[dim]·[/]"
                    for x in self._img_slots
                )
                detail = f"{grid}  {detail}"

            t.add_row(icon, f"[{style}]{name}[/]", t_str, detail)

        return Panel(t, border_style="bright_black", box=box.ROUNDED, padding=(0, 1))


def stats_table(data: dict[str, str]) -> Table:
    t = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    t.add_column("key", style="dim cyan", no_wrap=True)
    t.add_column("val", style="white")
    for k, v in data.items():
        t.add_row(k, v)
    return t
