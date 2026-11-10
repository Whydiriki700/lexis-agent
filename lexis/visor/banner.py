# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The locked horizontal banner: fire mascot at the left, LEXIS and
AGENT side by side in one band, BY OSVYN small underneath.
Artwork transcribed from the approved mockup (Master, 2026-11-10).
"""

from rich.text import Text

EMBER = "#ff7a29"
AMBER = "#e0a83c"
PALE = "#ffd9a0"
FAINT = "#6f5f4e"
DIM = "#a08b74"

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


def banner_text() -> Text:
    """Compose the horizontal banner as styled Rich text."""
    out = Text()
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
