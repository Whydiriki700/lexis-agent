# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The Visor's two themes (Master: Foxfire Ember locked
2026-11-10; the second theme ordered the same evening,
a blue kitsune fire that must be stronger than the first).

One palette table drives every surface: the Textual theme
and its CSS variables, the flame renderer, the banner and
panel accents, the emblems, and the syntax style, so a
switch recolors the whole face at once and the two themes
can never drift apart surface by surface. Foxfire's values
are the locked originals; Kitsune Azure answers them with
a deeper field, a seven-stop flame, and a white-hot core.
"""

FOXFIRE = "foxfire-ember"
AZURE = "kitsune-azure"
# Default theme (Master, 2026-11-21): Kitsune Azure is the
# default face. Foxfire Ember is unchanged and remains a
# full theme choice; a profile that already saved a choice
# keeps it, because this constant is only the fallback when
# no theme was ever saved.
DEFAULT = AZURE

THEMES = {
    FOXFIRE: {
        "label": "Foxfire Ember",
        "blurb": "the original foxfire",
        "primary": "#ff7a29",
        "accent": "#e0a83c",
        "background": "#0c0a08",
        "surface": "#171310",
        "panel": "#100d0a",
        "foreground": "#e8ded2",
        "css": {
            "ember": "#ff7a29", "amber": "#e0a83c",
            "bg": "#0c0a08", "pnl": "#171310",
            "pnl2": "#100d0a", "line": "#2b2118",
            "line2": "#3d2d1d", "txt": "#e8ded2",
            "dim": "#a08b74", "faint": "#6f5f4e",
            "green": "#3fb96f", "red": "#e05c5c",
        },
        "ember": "#ff7a29", "amber": "#e0a83c",
        "pale": "#ffd9a0", "faint": "#6f5f4e",
        "dim": "#a08b74",
        "syntax_bg": "#0a0806",
    },
    AZURE: {
        "label": "Kitsune Azure",
        "blurb": "blue kitsune fire",
        "primary": "#38bdf8",
        "accent": "#7dd3fc",
        "background": "#060a13",
        "surface": "#0b1322",
        "panel": "#081020",
        "foreground": "#e6f2ff",
        "css": {
            "ember": "#38bdf8", "amber": "#7dd3fc",
            "bg": "#060a13", "pnl": "#0b1322",
            "pnl2": "#081020", "line": "#1c2f52",
            "line2": "#2a4a7f", "txt": "#e6f2ff",
            "dim": "#8fb0d8", "faint": "#5b7bab",
            "green": "#3fb96f", "red": "#e05c5c",
        },
        "ember": "#38bdf8", "amber": "#7dd3fc",
        "pale": "#e0f2fe", "faint": "#5b7bab",
        "dim": "#8fb0d8",
        "syntax_bg": "#05080f",
    },
}
