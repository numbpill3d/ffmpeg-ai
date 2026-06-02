"""Pipeline tracker and stats widgets."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .display import C_ACCENT, C_CACHED, C_DIM, C_ERROR, C_MUTED, C_SUCCESS

console = Console(highlight=False)

# ── Stage states ──────────────────────────────────────────────────────────────

PENDING = "pending"
RUNNING = "running"
CACHED  = "cached"
DONE    = "done"
FAILED  = "failed"

# Braille spinner — animates on every _render() call while a stage is RUNNING
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_ICON: dict[str, str] = {
    PENDING: f"[{C_MUTED}] · [/]",
    CACHED:  f"[{C_CACHED}] ◉ [/]",
    DONE:    f"[{C_SUCCESS}] ✓ [/]",
    FAILED:  f"[{C_ERROR}] ✗ [/]",
}

# Row text style per state
_ROW_STYLE: dict[str, str] = {
    PENDING: C_MUTED,
    RUNNING: "white",
    CACHED:  C_CACHED,
    DONE:    "dim",           # done rows recede — running row stands out
    FAILED:  C_ERROR,
}

# ── Progress bar ──────────────────────────────────────────────────────────────

_BAR_W = 22
_BAR_FULL  = "█"
_BAR_EMPTY = "░"


def _bar(current: int, total: int) -> str:
    if total == 0:
        return f"[{C_DIM}]{'░' * _BAR_W}[/]"
    filled = int(_BAR_W * current / total)
    empty  = _BAR_W - filled
    return (
        f"[{C_ACCENT}]{'█' * filled}[/]"
        f"[{C_DIM}]{'░' * empty}[/]"
    )


# ── Image grid ────────────────────────────────────────────────────────────────

_IMG_DONE    = f"[{C_SUCCESS}]●[/]"
_IMG_PHOLDER = "[yellow]◐[/]"
_IMG_PENDING = f"[{C_MUTED}]○[/]"


def _img_grid(slots: list[str]) -> str:
    parts = []
    for s in slots:
        if s == "done":
            parts.append(_IMG_DONE)
        elif s == "placeholder":
            parts.append(_IMG_PHOLDER)
        else:
            parts.append(_IMG_PENDING)
    return "".join(parts)


# ── Stage dataclass ───────────────────────────────────────────────────────────

@dataclass
class _Stage:
    name: str
    status: str = PENDING
    detail: str = ""
    elapsed: float = 0.0
    progress: Optional[tuple[int, int]] = None
    _start: Optional[float] = field(default=None, repr=False)

    def tick(self) -> None:
        if self._start and self.status == RUNNING:
            self.elapsed = time.time() - self._start


# ── PipelineTracker ───────────────────────────────────────────────────────────

class PipelineTracker:
    """Context-manager that renders a live-updating pipeline stage table."""

    def __init__(self, stage_names: list[str], quiet: bool = False):
        self._order  = stage_names
        self._stages = {n: _Stage(n) for n in stage_names}
        self._quiet  = quiet
        self._live: Optional[Live] = None
        self._img_slots: list[str] = []
        self._frame = 0                 # incremented each render for spinner

    def __enter__(self) -> "PipelineTracker":
        if not self._quiet:
            self._live = Live(
                self._render(),
                console=console,
                refresh_per_second=12,
                transient=False,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.__exit__(*args)

    # ── stage control ─────────────────────────────────────────────────────────

    def start(self, name: str, detail: str = "") -> None:
        s = self._stages[name]
        s.status  = RUNNING
        s.detail  = detail
        s._start  = time.time()
        s.elapsed = 0.0
        self._refresh()

    def update(self, name: str, current: int, total: int, detail: str = "") -> None:
        s = self._stages[name]
        s.progress = (current, total)
        s.tick()
        if detail:
            s.detail = detail
        self._refresh()

    def complete(self, name: str, detail: str = "", cached: bool = False) -> None:
        s = self._stages[name]
        s.status   = CACHED if cached else DONE
        s.progress = None
        s.tick()
        if detail:
            s.detail = detail
        self._refresh()
        if self._quiet:
            icon   = "◉" if cached else "✓"
            t_str  = f"  {s.elapsed:.1f}s" if s.elapsed > 0 else ""
            print(f"  {icon}  {name:<12}{t_str}  {s.detail}")

    def fail(self, name: str, detail: str = "") -> None:
        s = self._stages[name]
        s.status = FAILED
        s.tick()
        if detail:
            s.detail = detail
        self._refresh()
        if self._quiet:
            print(f"  ✗  {name:<12}  {s.detail}")

    def print(self, renderable) -> None:
        """Print a renderable inside the live context."""
        if self._live:
            self._live.console.print(renderable)
        elif not self._quiet:
            console.print(renderable)

    # ── image grid ────────────────────────────────────────────────────────────

    def set_image_count(self, n: int) -> None:
        self._img_slots = ["pending"] * n

    def image_done(self, idx: int, is_placeholder: bool) -> None:
        if idx < len(self._img_slots):
            self._img_slots[idx] = "placeholder" if is_placeholder else "done"
        self._refresh()

    # ── rendering ─────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _running_stage(self) -> Optional[str]:
        for name in self._order:
            if self._stages[name].status == RUNNING:
                return name
        return None

    def _all_done(self) -> bool:
        return all(
            s.status in (DONE, CACHED, FAILED)
            for s in self._stages.values()
        )

    def _any_failed(self) -> bool:
        return any(s.status == FAILED for s in self._stages.values())

    def _border_style(self) -> str:
        if self._any_failed():
            return C_ERROR
        if self._all_done():
            return C_SUCCESS
        if self._running_stage():
            return C_ACCENT
        return C_DIM

    def _panel_title(self) -> str:
        running = self._running_stage()
        if running:
            return f"[{C_ACCENT}] {running.lower()} [/]"
        if self._all_done():
            return f"[{C_SUCCESS}] complete [/]"
        return ""

    def _render(self) -> Panel:
        self._frame += 1
        spin_char = _SPINNER[self._frame % len(_SPINNER)]

        t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
        t.add_column("icon",   width=4,  no_wrap=True)
        t.add_column("name",   width=11, no_wrap=True)
        t.add_column("time",   width=7,  no_wrap=True)
        t.add_column("detail", overflow="fold")

        for name in self._order:
            s = self._stages[name]
            s.tick()

            style  = _ROW_STYLE[s.status]
            t_str  = f"[dim]{s.elapsed:5.1f}s[/]" if s.elapsed > 0 else f"[{C_MUTED}]   –  [/]"

            if s.status == RUNNING:
                icon   = f"[bold {C_ACCENT}] {spin_char} [/]"
                name_s = f"[bold {C_ACCENT}]{name}[/]"
            else:
                icon   = _ICON.get(s.status, _ICON[PENDING])
                name_s = f"[{style}]{name}[/]"

            # Build detail string
            detail_parts: list[str] = []

            if s.progress is not None:
                cur, tot = s.progress
                detail_parts.append(_bar(cur, tot))
                detail_parts.append(f"  [{C_ACCENT}]{cur}/{tot}[/]")

            if name == "IMAGES" and self._img_slots:
                grid = _img_grid(self._img_slots)
                detail_parts.append(f"  {grid}")

            if s.detail:
                detail_parts.append(f"  [dim]{s.detail}[/]")

            detail_text = "".join(detail_parts).strip() or f"[{C_MUTED}]waiting[/]"

            t.add_row(icon, name_s, t_str, detail_text)

        return Panel(
            t,
            title      = self._panel_title(),
            title_align= "left",
            border_style= self._border_style(),
            box        = box.ROUNDED,
            padding    = (0, 1),
        )


# ── Stats table (post-completion summary) ─────────────────────────────────────

_BOLD_KEYS = {"output", "duration", "elapsed"}


def stats_table(data: dict[str, str]) -> Table:
    """Key-value summary table. Keys in _BOLD_KEYS get a bolder value style."""
    t = Table(
        box=box.SIMPLE,
        show_header=False,
        pad_edge=False,
        padding=(0, 2),
    )
    t.add_column("key", style=f"dim {C_ACCENT}", no_wrap=True, min_width=10)
    t.add_column("val", no_wrap=False)

    for k, v in data.items():
        if k in _BOLD_KEYS:
            val_markup = f"[bold white]{v}[/]"
        else:
            val_markup = f"[white]{v}[/]"
        t.add_row(k, val_markup)

    return t
