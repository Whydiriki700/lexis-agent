# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The Lexis icon set: original character emblems drawn for
Lexis alone, in the Foxfire Ember palette. Approved by Master,
2026-11-10: a burning brain for the Cortex, a burning skull for
INFERNO. These are not stock emoji and are never paired glyphs;
each emblem is one fused drawing."""

from rich.text import Text

from lexis.visor.banner import AMBER, EMBER, FAINT, PALE

_BRAIN = [
    ("   )  (   )", f"bold {EMBER}"),
    ("  (    ) (", AMBER),
    ("   (~~~~~)", PALE),
    ("  (~(o)~~(~)", PALE),
    ("  (~~(o)~)", PALE),
    ("   (_____)", PALE),
]

_SKULL = [
    ("   )  (   )", f"bold {EMBER}"),
    ("  (    ) (", AMBER),
    ('    .-"""-.', PALE),
    ("   / (o)(o)\\", PALE),
    ("   |   /\\   |", PALE),
    ("    \\ |  | /", PALE),
    ("     ‾‾‾‾‾", FAINT),
]


def _emblem(lines) -> Text:
    out = Text(overflow="crop")
    for i, (line, style) in enumerate(lines):
        if i:
            out.append("\n")
        out.append(line, style=style)
    return out


def brain_fire_text() -> Text:
    """The burning brain: Lexis Cortex's own mark."""
    return _emblem(_BRAIN)


def skull_fire_text() -> Text:
    """The burning skull: INFERNO's own mark."""
    return _emblem(_SKULL)
