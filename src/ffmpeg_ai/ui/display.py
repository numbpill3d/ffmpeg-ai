"""ASCII banner and pipeline status display."""
import random
import time
from rich.console import Console
from rich.text import Text
from rich.align import Align
from rich.live import Live

console = Console()

# Bottom row of the logo — used twice: once in blue, once offset-right as depth shadow
_BOTTOM = "  ╚═╝     ╚═╝     ╚═╝     ╚═╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝  ╚═╝╚═╝"

# Each row: (text, settled_style)
# Top row = brightest (light from above), blends darker toward base, shadow row last
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
    (" " + _BOTTOM, "dim blue"),   # perspective shadow — shifted 1 right
]

_NOISE = "╔╗╚╝╠╣║═╦╩╬█▓▒░│─┤├┼▀▄·:?"
_N = len(_LOGO)


def _static(n: int) -> str:
    return "".join(random.choice(_NOISE) for _ in range(n))


def _build(
    revealed_dim: int,    # rows fully shown (dim blue — pass-1 state)
    revealed_lit: int,    # rows shown in true color (pass-2 state, counts from bottom)
    beam: int = -1,       # index of the bright beam row
    glitch: set[int] | None = None,
) -> Text:
    """Compose one frame. Two revelation states model the two-pass CRT effect."""
    t = Text()
    g = glitch or set()
    for i, (line, style) in enumerate(_LOGO):
        if i in g:
            t.append(_static(len(line)) + "\n", style="dim cyan")
        elif i >= _N - revealed_lit:
            # pass-2: true color revealed (bottom rows light up first in upward pass)
            t.append(line + "\n", style=style)
        elif i < revealed_dim:
            # pass-1: revealed but not yet lit
            t.append(line + "\n", style="dim blue")
        elif i == beam:
            t.append(line + "\n", style="bold bright_white")
        else:
            t.append(_static(len(line)) + "\n", style="dim blue")
    return t


def print_banner() -> None:
    _subtitle = (
        "\n  ai · video · ffmpeg  ─  free providers · shorts & landscape\n"
    )

    with Live(
        Align.center(_build(0, 0, beam=0)),
        console=console,
        refresh_per_second=24,
        transient=False,
    ) as live:

        # ── pass 1: dim scanline sweeps top → bottom ─────────────────────────
        for beam in range(_N + 1):
            live.update(Align.center(_build(max(0, beam - 1), 0, beam=beam)))
            time.sleep(0.05)

        # ── pass 2: color scanline sweeps bottom → top ───────────────────────
        for lit in range(_N + 1):
            # beam index during upward pass (starts at bottom, moves up)
            up_beam = (_N - 1) - lit
            live.update(Align.center(_build(_N, lit, beam=up_beam if lit < _N else -1)))
            time.sleep(0.06)

        # ── glitch flicker ───────────────────────────────────────────────────
        for _ in range(6):
            bad = {i for i in range(_N - 1) if random.random() < 0.18}
            live.update(Align.center(_build(_N, _N, glitch=bad)))
            time.sleep(0.038)

        # ── settle ───────────────────────────────────────────────────────────
        final = _build(_N, _N)
        final.append(_subtitle, style="dim white")
        live.update(Align.center(final))
