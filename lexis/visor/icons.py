# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The Lexis icon set: original character emblems drawn for
Lexis alone, in the Foxfire Ember palette. Approved by Master,
2026-11-10: a burning brain for the Cortex, a burning skull for
INFERNO. These are not stock emoji and are never paired glyphs;
each emblem is one fused drawing."""

from rich.text import Text

from lexis.visor import banner


def _brain_lines():
    # Built per call so the emblem follows the active
    # theme's colors (Master, 2026-11-10); the drawing
    # itself never changes.
    return [
        ("   )  (   )", f"bold {banner.EMBER}"),
        ("  (    ) (", banner.AMBER),
        ("   (~~~~~)", banner.PALE),
        ("  (~(o)~~(~)", banner.PALE),
        ("  (~~(o)~)", banner.PALE),
        ("   (_____)", banner.PALE),
    ]


def _skull_lines():
    return [
        ("   )  (   )", f"bold {banner.EMBER}"),
        ("  (    ) (", banner.AMBER),
        ('    .-"""-.', banner.PALE),
        ("   / (o)(o)\\", banner.PALE),
        ("   |   /\\   |", banner.PALE),
        ("    \\ |  | /", banner.PALE),
        ("     ‾‾‾‾‾", banner.FAINT),
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
    return _emblem(_brain_lines())


def skull_fire_text() -> Text:
    """The burning skull: INFERNO's own mark."""
    return _emblem(_skull_lines())
