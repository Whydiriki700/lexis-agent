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
                    # Wait for the approve BUTTON, not just the
                    # screen class: under load the class can
                    # register a beat before its DOM mounts, and
                    # querying earlier races the compose.
                    def approve_ready():
                        try:
                            return len(
                                app.screen.query("#approve")) > 0
                        except Exception:
                            return False

                    self.assertTrue(
                        await wait_for(approve_ready),
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
                    # Tool status lives on the activity strip,
                    # never as a card inside the chat (Master,
                    # 2026-11-11).
                    self.assertFalse(app.query(".card"))
                    activity = str(
                        app.query_one("#activity").render())
                    self.assertIn("Write file", activity)
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


class StopCommandTest(unittest.IsolatedAsyncioTestCase):
    """Master's urgent revision (2026-11-10): /stop is an
    official command equal to Esc, it never queues, and the
    flame dims to low ember instead of vanishing."""

    async def test_stop_command_stops_and_dims_out(self):
        import time as _time

        orig = bridge.stream_chat

        def fake(model, messages, key):
            for i in range(600):
                _time.sleep(0.02)
                yield f"t{i} "

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    from lexis.visor.app import PALETTE_COMMANDS

                    self.assertIn(
                        "/stop",
                        [c[0] for c in PALETTE_COMMANDS],
                    )
                    app.submit_text("cerita yang sangat panjang")
                    self.assertTrue(
                        await wait_for(lambda: app.busy)
                    )
                    app.submit_text("/stop")
                    self.assertTrue(
                        await wait_for(
                            lambda: not app.busy, timeout=20
                        ),
                        "/stop did not stop the turn",
                    )
                    typing_w = app.query_one("#typing")
                    self.assertTrue(
                        await wait_for(
                            lambda: not typing_w.has_class("on"),
                            timeout=10,
                        ),
                        "the flame never dimmed out",
                    )
                    status = str(
                        app.query_one("#status").render()
                    )
                    self.assertIn("Ember low", status)
        finally:
            bridge.stream_chat = orig

    async def test_stop_drops_the_queue_and_reports(self):
        import time as _time

        orig = bridge.stream_chat

        def fake(model, messages, key):
            for i in range(600):
                _time.sleep(0.02)
                yield f"t{i} "

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("kerjaan pertama")
                    self.assertTrue(
                        await wait_for(lambda: app.busy))
                    app.submit_text("kerjaan kedua antre")
                    await pilot.pause()
                    self.assertEqual(len(app.queue), 1)
                    app.submit_text("/stop")
                    self.assertEqual(len(app.queue), 0)
                    self.assertIn("dropped", chat_text(app))
                    self.assertTrue(
                        await wait_for(
                            lambda: not app.busy, timeout=20))
        finally:
            bridge.stream_chat = orig


class TypingFlameTest(unittest.IsolatedAsyncioTestCase):
    """The flame strip stays lit and MOVES while the reply
    streams (Master's revision, 2026-11-10): the first token
    must not retire it, and successive frames differ."""

    async def test_flames_live_during_streaming(self):
        import time as _time

        orig = bridge.stream_chat

        def fake(model, messages, key):
            for i in range(300):
                _time.sleep(0.03)
                yield f"w{i} "

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("cerita panjang")
                    self.assertTrue(
                        await wait_for(lambda: app.busy))
                    self.assertTrue(
                        await wait_for(
                            lambda: len(app._stream_buf) > 30),
                        "the stream never started",
                    )
                    typing_w = app.query_one("#typing")
                    self.assertTrue(
                        typing_w.has_class("on"),
                        "flame strip retired at the first token",
                    )
                    first = str(typing_w.render())
                    await pilot.pause(1.2)
                    second = str(typing_w.render())
                    self.assertNotEqual(
                        first, second,
                        "the flame strip is frozen mid-stream",
                    )
                    app.submit_text("/stop")
                    self.assertTrue(
                        await wait_for(
                            lambda: not app.busy, timeout=20))
        finally:
            bridge.stream_chat = orig


class StatusStripTest(unittest.TestCase):
    """Hermes status discipline (2026-11-10): flame state,
    model, and context are pinned; tail segments drop whole,
    in order, as the width narrows."""

    def _status(self, width):
        from lexis.visor import panels

        return panels.status_text(
            model="deepseek-v4.1-flash-1017-fast",
            provider="Osvyn", mode="EMBER", mode_icon="🔥",
            conn="linked", state_icon="◦",
            state_label="Ember low · idle",
            turn_in=1200, turn_out=300, live=False,
            sess_total=1500, ctx_pct=12, turn_secs=3.2,
            queued=0, width=width,
        ).plain

    def test_wide_keeps_everything(self):
        text = self._status(0)
        for needle in ("Provider", "Session cost", "Autosaved",
                       "Ember low", "Context"):
            self.assertIn(needle, text)

    def test_narrow_drops_tail_whole_keeps_pinned(self):
        text = self._status(44)
        for pinned in ("Ember low", "deepseek", "Context"):
            self.assertIn(pinned, text)
        for dropped in ("Autosaved", "Session cost", "Provider"):
            self.assertNotIn(dropped, text)


class SessionCycleTest(unittest.IsolatedAsyncioTestCase):
    """/new and /start (Master, 2026-11-10): /new opens a clean
    session with a new ledger id and never touches the old one;
    /start reports the lit session."""

    async def test_new_session_fresh_id_old_untouched(self):
        orig = bridge.stream_chat

        def fake(model, messages, key):
            yield "jawaban sesi lama"

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(150, 48)) as pilot:
                    await pilot.pause()
                    old_id = app.session_id
                    app.submit_text("halo sesi lama")
                    self.assertTrue(
                        await wait_for(lambda: not app.busy))
                    app.submit_text("/new")
                    await pilot.pause()
                    self.assertNotEqual(app.session_id, old_id)
                    old_msgs = app.ledger.load_messages(old_id)
                    self.assertTrue(
                        any("halo sesi lama" in m["content"]
                            for m in old_msgs),
                        "the old session lost its history",
                    )
                    new_msgs = app.ledger.load_messages(
                        app.session_id)
                    self.assertFalse(
                        any("halo sesi lama" in m["content"]
                            for m in new_msgs),
                        "the new session inherited old messages",
                    )
                    self.assertIn("New session lit", chat_text(app))
        finally:
            bridge.stream_chat = orig

    async def test_start_reports_the_lit_session(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(150, 48)) as pilot:
                await pilot.pause()
                app.submit_text("/start")
                await pilot.pause()
                self.assertIn("Work session lit", chat_text(app))


class SyntaxLiveTest(unittest.IsolatedAsyncioTestCase):
    """Rich Syntax for the code surfaces + ONE clock (Master,
    2026-11-11): the reveal rides the flame clock, no second
    timer may exist."""

    def test_code_text_is_rich_syntax_with_foxfire_theme(self):
        from rich.syntax import Syntax

        from lexis.visor.app import FoxfireSyntaxStyle, code_text
        syn = code_text("def ember():\n    return 1\n",
                        path="x.py")
        self.assertIsInstance(syn, Syntax)
        self.assertEqual("Python", syn.lexer.name)
        md = code_text("# Title\n", path="notes.md")
        self.assertEqual("Markdown", md.lexer.name)
        self.assertEqual("#0a0806",
                         FoxfireSyntaxStyle.background_color)

    async def test_finished_write_shows_whole_no_replay(self):
        # Master, 2026-11-11: live coding must be truly live,
        # never a staged replay. A finished write handed to the
        # panel shows whole, at once, with no timer behind it.
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(2.2)
                app._start_live(
                    "big.py",
                    "\n".join(f"line_{i} = {i}" for i in range(60)))
                self.assertEqual(60, app._live["revealed"])
                self.assertEqual(60, app._live["total"])
                self.assertFalse(app._live["streaming"])
                self.assertFalse(hasattr(app, "_live_timer"))
                app._finish_live()
                self.assertIsNone(app._live)


class LiveStreamTest(unittest.IsolatedAsyncioTestCase):
    """Live coding is the stream itself (Master, 2026-11-11):
    while the model is still writing the marker, the panel
    already shows the file as far as it exists."""

    async def test_panel_follows_the_stream(self):
        import time as _time

        orig = bridge.stream_chat
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "streamed.py")

            def fake(model, messages, key):
                yield (
                    "Writing it now.\n[WRITE_FILE: "
                    + target + "]\nline one\n"
                )
                _time.sleep(0.8)
                yield "line two\n"
                _time.sleep(0.8)
                yield "line three\n[/WRITE_FILE]\ndone"

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                app.always_write = True
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("write the file")
                    self.assertTrue(
                        await wait_for(
                            lambda: app._live is not None
                            and app._live.get("streaming")
                            and "line one"
                            in app._live["content"]
                        ),
                        "panel never followed the stream",
                    )
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish",
                    )
                    await pilot.pause()
                    with open(target, encoding="utf-8") as f:
                        self.assertIn("line three", f.read())
                    activity = str(
                        app.query_one("#activity").render())
                    self.assertIn("Write file", activity)
                    self.assertIn("✓", activity)
                    self.assertNotIn("Write file ·",
                                     chat_text(app))
            finally:
                bridge.stream_chat = orig


class ClipboardTest(unittest.IsolatedAsyncioTestCase):
    """Ctrl+C / Ctrl+V / Ctrl+X in every entry (Master,
    2026-11-11, without exception)."""

    def test_clipboard_roundtrip_when_available(self):
        from lexis.visor import clipboard as cb

        if not cb.set_text("lexis-clip-probe"):
            self.skipTest("no clipboard in this session")
        self.assertEqual("lexis-clip-probe", cb.get_text())

    async def test_keys_work_in_composer_and_palette_input(self):
        from lexis.visor import clipboard as cb

        store = {"text": "PASTED-TOKEN"}
        orig_get, orig_set = cb.get_text, cb.set_text
        cb.get_text = lambda: store["text"]
        cb.set_text = (
            lambda t: store.__setitem__("text", t) or True)
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(120, 40)) as pilot:
                    await pilot.pause(1.5)
                    composer = app.query_one("#composer")
                    composer.focus()
                    await pilot.press("ctrl+v")
                    await pilot.pause()
                    self.assertIn("PASTED-TOKEN", composer.text)
                    await pilot.press("ctrl+a")
                    await pilot.press("ctrl+c")
                    self.assertEqual("PASTED-TOKEN", store["text"])
                    await pilot.press("ctrl+x")
                    await pilot.pause()
                    self.assertEqual("", composer.text)
                    await pilot.press("ctrl+k")
                    await pilot.pause()
                    entry = app.screen.query_one("#pal-q")
                    entry.focus()
                    store["text"] = "help"
                    await pilot.press("ctrl+v")
                    await pilot.pause()
                    self.assertIn("help", entry.value)
        finally:
            cb.get_text, cb.set_text = orig_get, orig_set


class BlazeVisorTest(unittest.IsolatedAsyncioTestCase):
    """BLAZE in the real Visor: the approval screen appears
    exactly once, carrying the one-warning text, and the
    second write of the same turn proceeds on its own."""

    async def test_blaze_warns_once_in_the_visor(self):
        orig = bridge.stream_chat
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.py")
            b = os.path.join(d, "b.py")
            calls = []

            def fake(model, messages, key):
                calls.append(1)
                if len(calls) == 1:
                    yield (
                        f"[WRITE_FILE: {a}]print('a')\n[/WRITE_FILE]\n"
                        f"[WRITE_FILE: {b}]print('b')\n[/WRITE_FILE]"
                    )
                else:
                    yield "both written"

            bridge.stream_chat = fake
            try:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app._set_mode("BLAZE")
                    pushes = []
                    warnings = []
                    orig_push = app.push_screen

                    def counting(screen, callback=None, **kw):
                        pushes.append(screen.__class__.__name__)
                        if screen.__class__.__name__ == "ApprovalScreen":
                            warnings.append(screen.warning)
                        return orig_push(screen, callback, **kw)

                    app.push_screen = counting

                    async def _approve_first():
                        for _ in range(60):
                            await asyncio.sleep(0.5)
                            if (app.screen.__class__.__name__
                                    == "ApprovalScreen"):
                                from textual.widgets import Button

                                app.screen.query_one(
                                    "#approve", Button).press()
                                return

                    asyncio.ensure_future(_approve_first())
                    app.submit_text("write both files")
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish",
                    )
                    self.assertEqual(["ApprovalScreen"], pushes)
                    self.assertEqual(1, len(warnings))
                    self.assertIn("one warning", warnings[0])
                    self.assertTrue(os.path.isfile(a))
                    self.assertTrue(os.path.isfile(b))
            finally:
                bridge.stream_chat = orig


class VisorCopyTest(unittest.IsolatedAsyncioTestCase):
    """Bug 2 (Master, 2026-11-11): conversation text must be
    copyable OUT of the chat: selectable widgets, /copy for
    the last reply, /copy all for the transcript."""

    async def test_copy_paths_and_selectable_chat(self):
        from lexis.cortex import bridge as _bridge
        from lexis.visor import clipboard as _clip

        captured = []
        old_set = _clip.set_text
        _clip.set_text = lambda text: captured.append(text) or True
        old_stream = _bridge.stream_chat

        def stream(model, messages, key):
            yield "Jawaban penting untuk disalin."

        _bridge.stream_chat = stream
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("halo")
                    self.assertTrue(
                        await wait_for(
                            lambda: not app.busy
                            and "Jawaban penting" in chat_text(app)
                        ),
                        "the turn never finished",
                    )
                    msgs = app.query("#chat .msg")
                    self.assertTrue(len(msgs) > 0)
                    self.assertTrue(
                        all(w.allow_select for w in msgs),
                        "chat messages are not selectable",
                    )
                    app.submit_text("/copy")
                    self.assertTrue(
                        await wait_for(
                            lambda: "Copied Lexis's last reply"
                            in chat_text(app)
                        ),
                        "/copy never reported",
                    )
                    self.assertEqual(
                        ["Jawaban penting untuk disalin."], captured)
                    app.submit_text("/copy all")
                    self.assertTrue(
                        await wait_for(
                            lambda: len(captured) == 2),
                        "/copy all never copied",
                    )
                    self.assertIn("YOU: halo", captured[1])
                    self.assertIn(
                        "LEXIS: Jawaban penting", captured[1])
        finally:
            _clip.set_text = old_set
            _bridge.stream_chat = old_stream

    async def test_ctrl_c_prefers_screen_selection(self):
        """Focus sits in the composer while the owner selects
        conversation text with the mouse; Ctrl+C must copy
        the screen selection, not the empty composer
        (Master, 2026-11-11: copy still felt broken after
        the first fix)."""
        from lexis.visor import clipboard as _clip

        captured = []
        old_set = _clip.set_text
        _clip.set_text = lambda text: captured.append(text) or True
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    from lexis.visor.app import Composer

                    app.query_one("#composer", Composer).focus()
                    app.screen.get_selected_text = (
                        lambda: "teks hasil seleksi")
                    await pilot.press("ctrl+c")
                    await pilot.pause()
                    self.assertEqual(
                        ["teks hasil seleksi"], captured)
        finally:
            _clip.set_text = old_set


class ApprovalLayoutTest(unittest.IsolatedAsyncioTestCase):
    """Master's screenshot (2026-11-11): with a long diff the
    approval modal's buttons were pushed out of the box and
    the owner had no way to answer. The diff now scrolls in
    its own region; the buttons must stay on screen even on
    a short terminal, and the diff itself must be copyable."""

    async def test_buttons_stay_visible_with_long_diff(self):
        from textual.widgets import Button

        from lexis.visor.app import ApprovalScreen

        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "code.py")
            with open(target, "w", encoding="utf-8") as f:
                f.write("\n".join(
                    f"line {i} = {i}" for i in range(80)) + "\n")
            app = LexisVisor(root=d)
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                self.assertTrue(
                    app.query_one("#livecode").allow_select,
                    "the live panel is not selectable",
                )
                new = "\n".join(
                    f"line {i} = {i + 1000}"
                    for i in range(80)) + "\n"
                app.push_screen(ApprovalScreen(target, new))
                await pilot.pause()
                self.assertEqual(
                    "ApprovalScreen",
                    app.screen.__class__.__name__)
                for bid in ("#approve", "#reject"):
                    btn = app.screen.query_one(bid, Button)
                    self.assertLessEqual(
                        btn.region.bottom, app.size.height,
                        f"{bid} is pushed off screen")
                    self.assertGreaterEqual(btn.region.y, 0)
                statics = app.screen.query(".diffscroll Static")
                self.assertTrue(len(statics) > 0)
                self.assertTrue(
                    all(w.allow_select for w in statics),
                    "the diff is not selectable")
                app.screen.query_one("#approve", Button).press()
                await pilot.pause()
                self.assertNotEqual(
                    "ApprovalScreen",
                    app.screen.__class__.__name__)


class VisorEvolveTest(unittest.IsolatedAsyncioTestCase):
    """Step 3 surfaces: /evolve refuses without verified work,
    and /skills approve activates a pending draft."""

    def seed_draft(self, root):
        path = os.path.join(root, "skills", "house-style",
                            "SKILL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: house-style\n"
                "description: the house style\n"
                "version: 1\n"
                "source: evolve\n"
                "---\n\n## Steps\n1. Write.\n"
            )

    async def test_evolve_gate_and_skills_approve(self):
        with tempfile.TemporaryDirectory() as d:
            self.seed_draft(d)
            app = LexisVisor(root=d)
            async with app.run_test(size=(130, 48)) as pilot:
                await pilot.pause()
                app.submit_text("/evolve fresh-one")
                self.assertTrue(
                    await wait_for(
                        lambda: "no verified success"
                        in chat_text(app)
                    ),
                    "evolve never reported the evidence gate",
                )
                app.submit_text("/skills approve house-style")
                await pilot.pause()
                self.assertTrue(
                    await wait_for(
                        lambda: "approved and active"
                        in chat_text(app)
                    ),
                    "approval never landed",
                )
                self.assertEqual(
                    "active",
                    app.pulse.skills.status_of("house-style"),
                )


class PlainWordsTest(unittest.TestCase):
    """No kitchen words on the user's surface (Master,
    2026-11-11): raw errnos and internal tool names are
    translated before display."""

    def test_plain_detail_translates_errno(self):
        from lexis.visor.app import _plain_detail

        self.assertEqual(
            _plain_detail(
                "[Errno 2] No such file or directory: "
                "'workspace/x.py'"),
            "the file does not exist")
        self.assertEqual(
            _plain_detail("128 lines · 4.2 KB"),
            "128 lines · 4.2 KB")

    def test_plan_text_renders_fail_cross(self):
        from lexis.visor import panels

        t = panels.plan_text([("fail", "Run tests x")])
        self.assertIn("✗", t.plain)

    def test_plain_reason_scrubs_judge_text(self):
        from lexis.visor.app import _plain_reason

        out = _plain_reason(
            "A step did not complete: read_file "
            "([Errno 2] No such file or directory: 'a.txt')")
        self.assertIn("Read file", out)
        self.assertIn("the file does not exist", out)
        self.assertNotIn("Errno", out)
        self.assertNotIn("read_file", out)


class ModelSwitchBusyPilotTest(unittest.IsolatedAsyncioTestCase):
    """A mid-task /model switch lands immediately and steers
    the next step (bug, Master 2026-11-11); it never queues
    behind the running work."""

    async def test_model_switch_applies_while_busy(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(130, 48)) as pilot:
                await pilot.pause()
                others = [m for m in app.compass.list_models()
                          if m != app.compass.current]
                self.assertTrue(others)
                app.busy = True
                try:
                    app.submit_text(f"/model {others[0]}")
                    await pilot.pause()
                    self.assertEqual(app.compass.current,
                                     others[0])
                    self.assertFalse(app.compass.auto)
                    self.assertEqual(len(app.queue), 0)
                    self.assertIn("next step", chat_text(app))
                finally:
                    app.busy = False


class PlanHonestyPilotTest(unittest.IsolatedAsyncioTestCase):
    """A failed tool marks its plan step with a cross, never
    a green tick (Master, 2026-11-11)."""

    async def test_failed_tool_marks_step_fail(self):
        with tempfile.TemporaryDirectory() as d:
            app = LexisVisor(root=d)
            async with app.run_test(size=(130, 48)) as pilot:
                await pilot.pause()
                app._on_event_ui("tool_start", {
                    "name": "run_command", "path": "dir",
                })
                app._on_event_ui("tool_end", {
                    "name": "run_command", "path": "dir",
                    "ok": False, "detail": "exit=1",
                    "duration": 0.2,
                })
                await pilot.pause()
                states = [s for s, _ in app.plan_steps]
                self.assertIn("fail", states)
                self.assertNotIn("now", states)


if __name__ == "__main__":
    unittest.main()
