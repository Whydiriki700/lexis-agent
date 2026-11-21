# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The locked Foxfire Ember flame language (design lock
2026-11-10), refined for smoothness on Master's direct review
(2026-11-11): the motion runs on one fine animation clock
(~90 ms), every value is interpolated, and no level ever snaps.
Tongue heights come from smooth value noise sampled on a fine
ladder, colors are lerped across the ember palette, particles
rise and fade by life fraction, and phase changes and the
/stop dim are eased ramps, not cuts. The irregular flicker
stays; only its steps became small enough to read as motion.

Reduced motion renders one static frame: the language is
present, the movement is not.
"""

import math

from rich.text import Text

PALE = "#FFD9A0"
AMBER = "#E0A83C"
HOT = "#FF9A3C"
EMBER = "#FF7A29"
DEEP = "#E85D04"
COOL = "#8A5A33"
ASH = "#5A4632"

_LADDER = "▁▂▃▄▅▆▇█"
_STOPS = (
    (0.0, (232, 93, 4)),
    (0.35, (255, 122, 41)),
    (0.6, (255, 154, 60)),
    (0.8, (224, 168, 60)),
    (1.0, (255, 217, 160)),
)

# Theme palettes (Master, 2026-11-10: the second theme,
# a blue kitsune fire stronger than the first). Foxfire is
# the locked original above. Azure answers with seven
# stops instead of five and a white-hot core: more ladder
# to lerp across, so its motion reads richer at the same
# clock. set_palette rebinds the module colors; every
# renderer reads them at call time.
_PALETTES = {
    "foxfire-ember": {
        "stops": _STOPS,
        "PALE": PALE, "AMBER": AMBER, "HOT": HOT,
        "EMBER": EMBER, "DEEP": DEEP, "COOL": COOL,
        "ASH": ASH,
    },
    "kitsune-azure": {
        "stops": (
            (0.0, (30, 64, 175)),
            (0.2, (29, 78, 216)),
            (0.4, (37, 99, 235)),
            (0.58, (56, 150, 248)),
            (0.72, (56, 189, 248)),
            (0.86, (147, 197, 253)),
            (1.0, (240, 249, 255)),
        ),
        "PALE": "#E0F2FE", "AMBER": "#7DD3FC",
        "HOT": "#BAE6FD", "EMBER": "#38BDF8",
        "DEEP": "#2563EB", "COOL": "#1E40AF",
        "ASH": "#33507A",
    },
}


def set_palette(name: str) -> None:
    pal = _PALETTES.get(name)
    if pal is None:
        return
    g = globals()
    g["_STOPS"] = pal["stops"]
    for key in ("PALE", "AMBER", "HOT", "EMBER", "DEEP",
                "COOL", "ASH"):
        g[key] = pal[key]
    cache = g.get("_glow_cache")
    if cache is not None:
        cache.clear()


def _noise(n: int) -> float:
    """Deterministic 0..1 noise from an integer (xorshift)."""
    x = (n * 2654435761 + 1013904223) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1103515245 + 12345) & 0xFFFFFFFF
    x ^= x >> 16
    return (x & 0xFFFF) / 65535.0


def _smooth(x: float) -> float:
    """Smooth value noise: lattice hashes lerped with a
    smootherstep curve, so consecutive samples move gradually."""
    i = int(math.floor(x))
    f = x - i
    u = f * f * f * (f * (f * 6 - 15) + 10)
    a, b = _noise(i), _noise(i + 1)
    return a + (b - a) * u


def _lerp_color(t: float) -> str:
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in zip(_STOPS, _STOPS[1:]):
        if t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            r = round(c0[0] + (c1[0] - c0[0]) * f)
            g = round(c0[1] + (c1[1] - c0[1]) * f)
            b = round(c0[2] + (c1[2] - c0[2]) * f)
            return f"#{r:02X}{g:02X}{b:02X}"
    return PALE


def _height(frame: int, phase: int, intensity: float) -> float:
    """Tongue height 0..1: a slow swell plus a faster flicker,
    both smooth, so the flame breathes instead of blinking."""
    swell = _smooth(frame * 0.045 + phase * 3.7)
    flick = _smooth(frame * 0.21 + phase * 9.1)
    return (0.55 * swell + 0.45 * flick) * intensity


def tongue(frame: int, phase: int, intensity: float = 1.0):
    """One flame tongue: (glyph, color) on the fine ladder."""
    if intensity <= 0.03:
        return "·", ASH
    h = _height(frame, phase, intensity)
    idx = min(7, int(h * 8.4))
    return _LADDER[idx], _lerp_color(h)


def _particles(frame: int, width: int, intensity: float):
    """Yield (column, row, glyph, color) for the embers alive
    at this frame. Each ember is born at the flame line, rises
    one row, and fades by life fraction; motion is stepped at
    the fine clock so the rise reads as continuous."""
    out = []
    count = int(26 * max(0.1, intensity))
    for i in range(count):
        birth = i * 4 + int(_noise(i * 91) * 6)
        life = 12 + int(_noise(i * 57) * 10)
        age = (frame - birth) % 34
        if age >= life:
            continue
        frac = age / life
        col = int(_noise(i * 131) * max(width - 1, 1))
        drift = round((_smooth(frame * 0.05 + i * 7.3) - 0.5) * 2)
        row = 1 if frac < 0.45 else 0  # born low, rises
        if frac < 0.3:
            glyph, color = "✦", _lerp_color(1.0 - frac)
        elif frac < 0.7:
            glyph, color = "•", _lerp_color(0.55 - frac * 0.3)
        else:
            glyph, color = "·", COOL
        out.append((max(0, col + drift), row, glyph, color))
    return out


def flame_rows(frame: int, width: int = 44,
               intensity: float = 1.0):
    """The particle cells (row, col, glyph, color), for the
    live coding panel's rising embers."""
    return _particles(frame, width, intensity)


def typing_text(frame: int, label: str = "Lexis is typing",
                intensity: float = 1.0,
                reduced: bool = False,
                phase: str = "typing") -> Text:
    """The typing strip below its separator: a particle row,
    then three tongues, the label, and staggered dots.

    Layered per phase (Hermes pattern): thinking breathes at a
    low smooth pulse, typing burns full tongues, working
    throws more sparks, a held flame freezes, and intensity
    below 1 is the eased dim toward low ember."""
    if reduced:
        frame = 0
    if phase == "held":
        frame = 6
    if phase == "thinking":
        intensity = intensity * (
            0.5 + 0.3 * _smooth(frame * 0.03))
    width = 46
    parts = _particles(frame, width, intensity)
    if phase == "working":
        parts = parts + _particles(frame + 11, width, intensity)
    top = [" "] * width
    top_style = {}
    for col, row, glyph, color in parts:
        if row == 0 and col < width:
            top[col] = glyph
            top_style[col] = color
    out = Text(no_wrap=True, overflow="crop")
    for i, ch in enumerate(top):
        out.append(ch, style=top_style.get(i) if ch != " " else None)
    out.append("\n")
    for phase_i in range(3):
        glyph, color = tongue(frame, phase_i, intensity)
        out.append(glyph, style=f"bold {color}")
        out.append(" ")
    out.append(label, style=AMBER)
    for d in range(3):
        bright = (frame // 3 + 2 - d) % 3 == 0 or reduced
        out.append(".", style=PALE if bright else COOL)
    return out


def glow_color(frame: int) -> str:
    """The warm status glow: a smooth pulse through the ember
    palette, lerped, never snapped between stops."""
    t = _smooth(frame * 0.06) * 0.6 + _smooth(frame * 0.017) * 0.4
    return _lerp_color(0.2 + 0.8 * t)


# One-cell status flame (Master, 2026-11-11): the ember lives
# in the status strip itself, moving while Lexis works and
# breathing low at idle. It is never absent: a user must be
# able to see at a glance that the fire is lit, and whether
# it is working or resting.
_BUSY_FRAMES = ("▂", "▃", "▅", "▇", "▅", "▃")
_IDLE_FRAMES = ("▁", "▁", "▂", "▁")


def status_flame(frame: int, busy: bool,
                 reduced: bool = False) -> str:
    if reduced:
        return "▂"
    if busy:
        return _BUSY_FRAMES[frame % len(_BUSY_FRAMES)]
    return _IDLE_FRAMES[(frame // 6) % len(_IDLE_FRAMES)]
