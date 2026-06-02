"""Console, banner animation, and shared display helpers."""
from __future__ import annotations

import random
import time

from rich.console import Console
from rich.rule import Rule
from rich.text import Text
from rich.align import Align
from rich.live import Live

console = Console(highlight=False)

# ── Brand palette (centralised so every module can import) ────────────────────
C_ACCENT   = "cyan"
C_DIM      = "bright_black"
C_SUCCESS  = "green"
C_WARN     = "yellow"
C_ERROR    = "red"
C_RUNNING  = "cyan"
C_CACHED   = "blue"
C_MUTED    = "dim"

# ── Banner ────────────────────────────────────────────────────────────────────

_BOTTOM = "  ╚═╝     ╚═╝     ╚═╝     ╚═╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝  ╚═╝╚═╝"

_LOGO: list[tuple[str, str]] = [
    (
        "  ███████╗███████╗███╗   ███╗██████╗ ███████╗ ██████╗      █████╗ ██╗",
        "bold bright_white",
    ),
    (
        "  ██╔════╝██╔════╝████╗ ████║██╔══██╗██╔════╝██╔════╝     ██╔══██╗██║",
        "white",
    ),
    (
        "  █████╗  █████╗  ██╔████╔██║██████╔╝█████╗  ██║  ███╗   ███████║██║",
        "bold cyan",
    ),
    (
        "  ██╔══╝  ██╔══╝  ██║╚██╔╝██║██╔═══╝ ██╔══╝  ██║   ██║   ██╔══██║██║",
        "cyan",
    ),
    (
        "  ██║     ██║     ██║ ╚═╝ ██║██║     ███████╗╚██████╔╝   ██║  ██║██║",
        "cyan",
    ),
    (_BOTTOM, "blue"),
    (" " + _BOTTOM, "dim blue"),
]

_NOISE = "╔╗╚╝╠╣║═╦╩╬█▓▒░│─┤├┼▀▄·:?"
_N = len(_LOGO)

_SUBTITLE = (
    "  generate · publish · automate"
    "  ─  zero cost  ·  free forever  ·  fully automated"
)


def _static(n: int) -> str:
    return "".join(random.choice(_NOISE) for _ in range(n))


def _build(
    revealed_dim: int,
    revealed_lit: int,
    beam: int = -1,
    glitch: set[int] | None = None,
) -> Text:
    t = Text()
    g = glitch or set()
    for i, (line, style) in enumerate(_LOGO):
        if i in g:
            t.append(_static(len(line)) + "\n", style="dim cyan")
        elif i >= _N - revealed_lit:
            t.append(line + "\n", style=style)
        elif i < revealed_dim:
            t.append(line + "\n", style="dim blue")
        elif i == beam:
            t.append(line + "\n", style="bold bright_white")
        else:
            t.append(_static(len(line)) + "\n", style="dim blue")
    return t


def print_banner() -> None:
    with Live(
        Align.center(_build(0, 0, beam=0)),
        console=console,
        refresh_per_second=24,
        transient=False,
    ) as live:
        for beam in range(_N + 1):
            live.update(Align.center(_build(max(0, beam - 1), 0, beam=beam)))
            time.sleep(0.045)

        for lit in range(_N + 1):
            up_beam = (_N - 1) - lit
            live.update(Align.center(_build(_N, lit, beam=up_beam if lit < _N else -1)))
            time.sleep(0.055)

        for _ in range(6):
            bad = {i for i in range(_N - 1) if random.random() < 0.18}
            live.update(Align.center(_build(_N, _N, glitch=bad)))
            time.sleep(0.035)

        final = _build(_N, _N)
        final.append("\n" + _SUBTITLE + "\n", style="dim white")
        live.update(Align.center(final))


# ── Shared message helpers ────────────────────────────────────────────────────

def rule(title: str = "", style: str = C_DIM) -> None:
    """Print a horizontal rule with an optional centred title."""
    console.print(Rule(title, style=style))


def header(title: str, subtitle: str = "") -> None:
    """Print a bold section header used by channel/auto commands."""
    console.print()
    if subtitle:
        console.print(f"[bold {C_ACCENT}]{title}[/]  [dim]{subtitle}[/]")
    else:
        console.print(f"[bold {C_ACCENT}]{title}[/]")


def success(msg: str) -> None:
    console.print(f"[bold {C_SUCCESS}]✓[/]  {msg}")


def error(msg: str) -> None:
    console.print(f"[bold {C_ERROR}]✗[/]  [bold {C_ERROR}]error:[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[{C_WARN}]⚠[/]  {msg}")


def info(msg: str) -> None:
    console.print(f"[{C_MUTED}]·[/]  [dim]{msg}[/]")


def bullet(msg: str) -> None:
    console.print(f"  [dim cyan]•[/] {msg}")
