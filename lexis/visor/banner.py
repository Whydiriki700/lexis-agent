# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The locked horizontal banner: fire mascot at the left, LEXIS and
AGENT side by side in one band, BY OSVYN small underneath.
Artwork transcribed from the approved mockup (Master, 2026-11-10).
The box-drawing glyph set is the locked original: an ASCII (#)
redraw was tried on 2026-11-10 and reverted the same evening on
Master's order ("yang semula aja"); do not redraw the wordmark.
"""

from rich.text import Text

EMBER = "#ff7a29"
AMBER = "#e0a83c"
PALE = "#ffd9a0"
FAINT = "#6f5f4e"
DIM = "#a08b74"


def set_colors(ember, amber, pale, faint, dim) -> None:
    """Theme switch (Master, 2026-11-10): the artwork and
    the wordmark never change; only their colors follow
    the active theme. The builders read these names at
    call time."""
    global EMBER, AMBER, PALE, FAINT, DIM
    EMBER, AMBER, PALE, FAINT, DIM = ember, amber, pale, faint, dim

MASCOT = [
    "        )",
    "       ) (",
    "      )   (",
    "     )     (",
    "    )   /\\   (",
    "   )   (  )   (",
    "    )   \\/   (",
    "     )     (",
    "      )   (",
    "       ) (",
]

LEXIS_ART = [
    "██╗     ███████╗██╗  ██╗██╗███████╗",
    "██║     ██╔════╝╚██╗██╔╝██║██╔════╝",
    "██║     █████╗   ╚███╔╝ ██║███████╗",
    "██║     ██╔══╝   ██╔██╗ ██║╚════██║",
    "███████╗███████╗██╔╝ ██╗██║███████╗",
    "╚══════╝╚══════╝╚═╝  ╚═╝╚═╝╚══════╝",
]

AGENT_ART = [
    " █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗",
    "██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝",
    "███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║",
    "██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║",
    "██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║",
    "╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝",
]

_MASCOT_W = 17

ART_WIDTH = max(
    _MASCOT_W + len(lexis) + 2 + len(agent)
    for lexis, agent in zip(LEXIS_ART, AGENT_ART)
)


def banner_compact_text() -> Text:
    """The narrow-window banner: same identity, small enough that
    the ASCII can never wrap and scramble (Master's report,
    2026-11-10: the wide art breaks in a small window)."""
    out = Text(overflow="crop")
    out.append("   ) (", style=AMBER)
    out.append("   LEXIS AGENT\n", style=f"bold {EMBER}")
    out.append("  ) /\\ (", style=AMBER)
    out.append("   BY OSVYN\n", style=FAINT)
    out.append("   )\\/ (", style=AMBER)
    out.append("   Lexis Cortex online", style=FAINT)
    return out


def banner_text() -> Text:
    """Compose the horizontal banner as styled Rich text."""
    out = Text(overflow="crop")
    for i in range(10):
        mascot = MASCOT[i] if i < len(MASCOT) else ""
        out.append(mascot.ljust(_MASCOT_W), style=AMBER)
        if i < 6:
            out.append(LEXIS_ART[i], style=f"bold {EMBER}")
            out.append("  ")
            out.append(AGENT_ART[i], style=f"bold {EMBER}")
        elif i == 6:
            out.append("BY OSVYN", style=FAINT)
        if i < 9:
            out.append("\n")
    return out
