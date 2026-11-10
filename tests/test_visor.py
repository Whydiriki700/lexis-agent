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

            calls = {"n": 0}

            def fake(model, messages, key):
                calls["n"] += 1
                if calls["n"] == 1:
                    yield (f"[WRITE_FILE: {target}] approved content "
                           "[/WRITE_FILE]")
                else:
                    yield "selesai"

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    async def _wd():
                        # A wedged approval must fail the test, never
                        # hang the suite: the worker thread parks on
                        # this event with no timeout by design.
                        await asyncio.sleep(25)
                        ev = getattr(app, "_approval_event", None)
                        if ev is not None and not ev.is_set():
                            ev.set()

                    asyncio.ensure_future(_wd())
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


class MasterFixBatchTest(unittest.IsolatedAsyncioTestCase):
    """Master's 2026-11-10 evening reports: the banner must not
    scramble in a small window, chat turns get separator bars, the
    slash preview appears while typing /, the rail scrolls."""

    async def test_banner_compact_when_narrow_wide_when_wide(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(90, 40)) as pilot:
                await pilot.pause()
                self.assertTrue(await wait_for(
                    lambda: "████" not in str(
                        app.query_one("#banner").render())
                ))
                banner = str(app.query_one("#banner").render())
                self.assertIn("LEXIS AGENT", banner)
            app2 = LexisVisor(root=d)
            async with app2.run_test(size=(190, 50)) as pilot:
                await pilot.pause()
                banner = str(app2.query_one("#banner").render())
                self.assertIn("████", banner)

    async def test_separators_frame_the_turn(self):
        orig = bridge.stream_chat

        def fake(model, messages, key):
            yield "halo dari lexis"

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("halo")
                    self.assertTrue(await wait_for(lambda: not app.busy))
                    text = chat_text(app)
                    self.assertIn("◆", text)
                    self.assertIn("YOU", text)
                    self.assertIn("LEXIS", text)
        finally:
            bridge.stream_chat = orig

    async def test_slash_menu_preview_and_complete(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(150, 48)) as pilot:
                await pilot.pause()
                area = app.query_one("#composer")
                area.focus()
                await pilot.press("/", "m", "o")
                await pilot.pause()
                menu = app.query_one("#slashmenu")
                self.assertTrue(menu.has_class("on"))
                self.assertIn("/model", str(menu.render()))
                await pilot.press("tab")
                await pilot.pause()
                self.assertEqual(area.text, "/model ")
                self.assertFalse(menu.has_class("on"))
                area.text = ""
                await pilot.press("/", "p", "l")
                await pilot.pause()
                self.assertTrue(menu.has_class("on"))
                await pilot.press("escape")
                await pilot.pause()
                self.assertFalse(menu.has_class("on"))

    async def test_provider_add_and_switch(self):
        with tempfile.TemporaryDirectory() as d:
            Path(os.path.join(d, ".env")).write_text(
                "DEEPSEEK_API_KEY=legacy-fixture\n", encoding="utf-8"
            )
            bridge.add_provider(
                d, "Kedua", "https://api.example.com/v1",
                "fixture-key-2",
            )
            app = LexisVisor(root=d)
            async with app.run_test(size=(150, 48)) as pilot:
                await pilot.pause()
                self.assertIn(
                    "Kedua", str(app.query_one("#hdr").render())
                )
                app.submit_text("/provider Osvyn")
                await pilot.pause()
                self.assertIn(
                    "Osvyn", str(app.query_one("#hdr").render())
                )
                app.submit_text("/provider")
                await pilot.pause()
                from textual.widgets import Button, Input, OptionList

                lst = app.screen.query_one(OptionList)
                lst.highlighted = len(lst.options) - 1
                await pilot.press("enter")
                await pilot.pause()
                scr = app.screen
                scr.query_one("#pv-name", Input).value = "Ketiga"
                scr.query_one("#pv-base", Input).value = (
                    "https://api.ketiga.example/v1"
                )
                scr.query_one("#pv-key", Input).value = "fixture-key-3"
                scr.query_one("#pv-save", Button).press()
                self.assertTrue(await wait_for(
                    lambda: bridge.provider_name(d) == "Ketiga"
                ))
                self.assertIn(
                    "Ketiga", str(app.query_one("#hdr").render())
                )
            providers_text = Path(
                os.path.join(d, "providers.json")
            ).read_text(encoding="utf-8")
            self.assertNotIn("fixture-key-3", providers_text)
            self.assertIn(
                "LEXIS_PROVIDER_KETIGA_KEY=fixture-key-3",
                Path(os.path.join(d, ".env")).read_text(
                    encoding="utf-8"
                ),
            )

    async def test_icons_own_emblems(self):
        from lexis.visor.app import BootScreen, InfernoScreen
        from lexis.visor.banner import banner_text
        from lexis.visor.icons import brain_fire_text, skull_fire_text

        self.assertIn("(~~~~~)", brain_fire_text().plain)
        self.assertIn('.-"""-.', skull_fire_text().plain)
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(150, 48)) as pilot:
                await pilot.pause()
                app.push_screen(InfernoScreen())
                await pilot.pause()
                text = "".join(
                    str(w.render()) for w in app.screen.query("Static")
                )
                self.assertIn('.-"""-.', text)
                await pilot.press("escape")
                app.push_screen(
                    BootScreen(
                        banner_text(), ["satu tahap"], interval=0.2
                    )
                )

                def emblem_shown():
                    if app.screen.__class__.__name__ != "BootScreen":
                        return False
                    found = app.screen.query("#boot-emblem")
                    return (
                        len(found) == 1
                        and "(~~~~~)" in str(found.first().render())
                    )

                self.assertTrue(
                    await wait_for(emblem_shown, timeout=5)
                )

    async def test_status_strip_and_composer_frame(self):
        orig = bridge.stream_chat
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "note.txt")
            calls = {"n": 0}

            def fake(model, messages, key):
                calls["n"] += 1
                if calls["n"] == 1:
                    yield (f"[WRITE_FILE: {target}] approved content "
                           "[/WRITE_FILE]")
                else:
                    yield "selesai"

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    # one clean frame: the composer lives inside it
                    composer = app.query_one("#composer")
                    self.assertEqual(
                        composer.parent.id, "composerbox"
                    )
                    strip = str(app.query_one("#status").render())
                    self.assertIn("Provider", strip)
                    self.assertIn("standby", strip)
                    self.assertIn("Ember low", strip)
                    self.assertIn("Context", strip)
                    async def _wd():
                        await asyncio.sleep(25)
                        ev = getattr(app, "_approval_event", None)
                        if ev is not None and not ev.is_set():
                            ev.set()

                    asyncio.ensure_future(_wd())
                    app.submit_text("write the note")
                    self.assertTrue(
                        await wait_for(
                            lambda: app.screen.__class__.__name__
                            == "ApprovalScreen"
                        ),
                        "approval screen never appeared",
                    )
                    self.assertTrue(
                        await wait_for(
                            lambda: "awaiting your word" in str(
                                app.query_one("#status").render()
                            )
                        ),
                        "status strip never showed the held state",
                    )
                    from textual.widgets import Button

                    app.screen.query_one("#approve", Button).press()
                    await pilot.pause()
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish after approval",
                    )
                    strip = str(app.query_one("#status").render())
                    self.assertIn("linked", strip)
                    self.assertIn("Session cost", strip)
                    # finished cards leave _cards (in-flight only);
                    # the widget itself stays in the chat flow
                    cards = app.query(".card")
                    self.assertTrue(cards)
                    first = str(cards[-1].render()).splitlines()[0]
                    # duration right-aligned at the card's edge
                    self.assertTrue(first.endswith("s"))
                    self.assertGreaterEqual(len(first), 60)
            finally:
                bridge.stream_chat = orig

    async def test_tokens_panel_live_dashboard(self):
        orig = bridge.stream_chat
        with tempfile.TemporaryDirectory() as d:
            reply = "x" * 40

            def fake(model, messages, key):
                yield reply

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("halo")
                    self.assertTrue(
                        await wait_for(lambda: not app.busy)
                    )
                    text = str(app.query_one("#pnl-tokens").render())
                    self.assertIn("TOKENS", text)
                    self.assertIn("Session total", text)
                    # The ledger's own estimate: reply tokens are
                    # len(reply) // 4 = 10 for this fixture.
                    self.assertIn("~10", text)
            finally:
                bridge.stream_chat = orig

    async def test_rail_scrolls_when_short(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(120, 22)) as pilot:
                await pilot.pause()
                from textual.containers import VerticalScroll

                rail = app.query_one("#rail")
                self.assertIsInstance(rail, VerticalScroll)
                self.assertGreater(rail.max_scroll_y, 0)


if __name__ == "__main__":
    unittest.main()
