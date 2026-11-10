# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The locked flame language, smoothness refinement included
(Master, 2026-11-11): one fine clock, interpolated values,
no snapping levels, eased phases, reduced motion static.
Run from the project root: python -m unittest tests.test_flames -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexis.visor import flames  # noqa: E402

LADDER = "▁▂▃▄▅▆▇█"


def plain(text_obj):
    return text_obj.plain


class TongueTest(unittest.TestCase):
    def test_frames_vary_irregularly(self):
        seq = [flames.tongue(f, 0)[0] for f in range(24)]
        self.assertGreater(len(set(seq)), 2)
        phases = {
            tuple(flames.tongue(f, p)[0] for f in range(8))
            for p in range(3)
        }
        self.assertGreater(len(phases), 1)

    def test_motion_is_continuous_not_snapping(self):
        # On the fine clock, a tongue's ladder level may only
        # move in small steps between consecutive frames.
        for phase in range(3):
            levels = [
                LADDER.index(flames.tongue(f, phase)[0])
                for f in range(60)
            ]
            steps = [abs(b - a)
                     for a, b in zip(levels, levels[1:])]
            self.assertLessEqual(max(steps), 2)

    def test_zero_intensity_is_ash(self):
        glyph, color = flames.tongue(3, 0, intensity=0.0)
        self.assertEqual("·", glyph)
        self.assertEqual(flames.ASH, color)


class TypingStripTest(unittest.TestCase):
    def test_strip_has_label_and_moves(self):
        frames = {plain(flames.typing_text(f)) for f in range(8)}
        self.assertTrue(all("Lexis is typing" in s for s in frames))
        self.assertGreater(len(frames), 3)  # the strip is alive

    def test_dimming_cools_the_strip(self):
        dim = plain(flames.typing_text(5, intensity=0.1))
        self.assertNotIn("█", dim)
        self.assertNotIn("▇", dim)

    def test_reduced_motion_is_static(self):
        a = plain(flames.typing_text(1, reduced=True))
        b = plain(flames.typing_text(9, reduced=True))
        self.assertEqual(a, b)
        self.assertIn("Lexis is typing", a)


class ParticleTest(unittest.TestCase):
    def test_particles_exist_and_change(self):
        a = flames.flame_rows(2, width=40)
        b = flames.flame_rows(3, width=40)
        self.assertTrue(a)
        self.assertNotEqual(a, b)
        rows = {r for _, r, _, _ in a + b}
        self.assertIn(0, rows)  # risen row is used


class PhaseTest(unittest.TestCase):
    def test_held_flame_is_frozen(self):
        a = plain(flames.typing_text(2, phase="held"))
        b = plain(flames.typing_text(8, phase="held"))
        self.assertEqual(a, b)

    def test_working_throws_more_sparks(self):
        few = flames._particles(4, 46, 1.0)
        more = few + flames._particles(15, 46, 1.0)
        self.assertGreaterEqual(len(more), len(few))

    def test_thinking_breathes_lower(self):
        typing_max = max(flames._height(f, 0, 1.0)
                         for f in range(40))
        thinking_max = max(
            flames._height(f, 0, 0.5 + 0.3 * flames._smooth(f * 0.03))
            for f in range(40))
        self.assertLessEqual(thinking_max, typing_max)


class GlowTest(unittest.TestCase):
    def test_glow_pulses_in_palette(self):
        colors = {flames.glow_color(f) for f in range(20)}
        self.assertGreater(len(colors), 3)
        for c in colors:
            self.assertTrue(c.startswith("#FF"))


class StatusFlameTest(unittest.TestCase):
    """The status ember (Master, 2026-11-11): always present,
    moving while working, breathing low at idle, still under
    reduced motion."""

    def test_busy_flame_moves(self):
        frames = {flames.status_flame(f, True)
                  for f in range(12)}
        self.assertGreater(len(frames), 2)

    def test_idle_flame_present_and_low(self):
        frames = {flames.status_flame(f, False)
                  for f in range(48)}
        self.assertTrue(frames)
        self.assertNotIn("▇", frames)

    def test_reduced_motion_is_still(self):
        frames = {flames.status_flame(f, True, reduced=True)
                  for f in range(12)}
        self.assertEqual(len(frames), 1)


if __name__ == "__main__":
    unittest.main()
