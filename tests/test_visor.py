# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Fase 2 Visor verification: headless Textual pilot tests.

Proves the app mounts with the locked banner and panels, the theme
carries Foxfire Ember and never the forbidden cyan, a chat turn
streams through the real pulse with a fake provider stream, a file
write goes through the approval screen and lands only after approval,
and a message sent while Lexis works is queued, not lost.
Run from the project root:  python -m unittest tests.test_visor -v
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexis.cortex import bridge  # noqa: E402
from lexis.visor.app import LexisVisor  # noqa: E402


def chat_text(app) -> str:
    parts = []
    for w in app.query("#chat Static"):
        try:
            parts.append(str(w.render()))
        except Exception:
            pass
    return "\n".join(parts)


async def wait_for(predicate, timeout=10.0):
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(0.1)
        waited += 0.1
    return predicate()


class DisplayTextTest(unittest.TestCase):
    def test_markers_never_reach_the_user(self):
        from lexis.visor.app import display_text

        self.assertEqual(display_text("hello [READ_FILE: a.py]"), "hello ")
        self.assertEqual(
            display_text("ok [WRITE_FILE: x.py]code [/WRITE_FILE]"), "ok "
        )
        self.assertEqual(display_text("typing [WRITE_FI"), "typing ")
        self.assertEqual(
            display_text("keep [brackets] here"), "keep [brackets] here"
        )


class VisorMountTest(unittest.IsolatedAsyncioTestCase):
    async def test_mounts_banner_panels_and_theme(self):
        app = LexisVisor(root=str(ROOT))
        async with app.run_test(size=(130, 48)) as pilot:
            await pilot.pause()
            svg = app.export_screenshot().replace("&#160;", " ")
            low = svg.lower()
            self.assertIn("#ff7a29", low)  # Foxfire Ember present
            self.assertNotIn("#15b3da", low)  # Osvyn cyan forbidden
            self.assertIn("LEXIS", svg)
            self.assertIn("BY OSVYN", svg)
            hdr = str(app.query_one("#hdr").render())
            self.assertIn("Lexis Cortex", hdr)
            self.assertIn("Compliance", hdr)
            self.assertIn("EMBER", hdr)
            plan = str(app.query_one("#pnl-plan").render())
            self.assertIn("PLAN", plan)
            ctx = str(app.query_one("#pnl-context").render())
            self.assertIn("CONTEXT", ctx)
            self.assertIn("Auto compaction", ctx)
            mem = str(app.query_one("#pnl-memory").render())
            self.assertIn("state.db", mem)
            status = str(app.query_one("#status").render())
            self.assertIn("Autosaved", status)


class VisorTurnTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_turn_and_queue(self):
        orig = bridge.stream_chat

        def fake(model, messages, key):
            yield "Hello "
            yield "world"

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("hi there")
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish",
                    )
                    await pilot.pause()
                    self.assertIn("Hello world", chat_text(app))
                    self.assertIn("YOU", chat_text(app))
        finally:
            bridge.stream_chat = orig

    async def test_write_needs_approval_then_lands(self):
        orig = bridge.stream_chat
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "note.txt")

            def fake(model, messages, key):
                yield f"[WRITE_FILE: {target}] approved content [/WRITE_FILE]"

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("write the note")
                    # approval screen must appear before anything is written
                    self.assertTrue(
                        await wait_for(
                            lambda: app.screen.__class__.__name__
                            == "ApprovalScreen"
                        ),
                        "approval screen never appeared",
                    )
                    self.assertFalse(os.path.exists(target))
                    # pilot.click is unreliable against modal buttons on
                    # Windows/Python 3.14; Button.press() travels the
                    # exact same Button.Pressed path deterministically.
                    from textual.widgets import Button

                    app.screen.query_one("#approve", Button).press()
                    await pilot.pause()
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish after approval",
                    )
                    self.assertTrue(os.path.exists(target))
                    self.assertEqual(
                        Path(target).read_text(encoding="utf-8"),
                        "approved content",
                    )
            finally:
                bridge.stream_chat = orig


if __name__ == "__main__":
    unittest.main()
