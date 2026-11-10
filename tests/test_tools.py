# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Full toolset verification (Master's build order, 2026-11-10):
forge handlers for edit/search/list/run/tests/fetch/browse, the
warden's exec gate, the pulse dispatch with its catalog injection,
and the judge/display protocol filters. Run from the project root:
python -m unittest tests.test_tools -v
"""

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexis.cortex import bridge  # noqa: E402
from lexis.cortex import forge as forge_mod  # noqa: E402
from lexis.cortex import judge as judge_mod  # noqa: E402
from lexis.cortex.compass import Compass  # noqa: E402
from lexis.cortex.forge import Forge  # noqa: E402
from lexis.cortex.ledger import Ledger  # noqa: E402
from lexis.cortex.pulse import CATALOG_MARK, Pulse  # noqa: E402
from lexis.cortex.vault import Vault  # noqa: E402
from lexis.cortex.warden import ALLOW, ASK, DENY, Warden  # noqa: E402

PY = f'"{sys.executable}"'


_OPEN_LEDGERS = []


def make_pulse(root, stream, mode="INFERNO"):
    ledger = Ledger(os.path.join(root, "state.db"))
    _OPEN_LEDGERS.append(ledger)
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])
    pulse = Pulse(
        root, Compass(), vault, Forge(), Warden(mode), ledger, sid,
        emit_token=lambda t: None, emit_line=lambda t: None,
        ask=lambda prompt: "y",
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, vault, old


class ForgeHandlersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.forge = Forge()

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_replaces_unique_passage(self):
        f = self.root / "a.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        self.forge.call("edit_file", path=str(f), old="x = 1",
                        new="x = 41")
        self.assertEqual("x = 41\ny = 2\n",
                         f.read_text(encoding="utf-8"))

    def test_edit_refuses_missing_and_duplicate(self):
        f = self.root / "a.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.forge.call("edit_file", path=str(f), old="zz",
                            new="q")
        with self.assertRaises(ValueError):
            self.forge.call("edit_file", path=str(f), old="x = 1",
                            new="q")

    def test_search_and_list(self):
        (self.root / "m.py").write_text(
            "NEEDLE = True\n", encoding="utf-8")
        (self.root / "n.txt").write_text("nothing\n", encoding="utf-8")
        hits = self.forge.call("search_text", pattern="NEEDLE",
                               root=str(self.root))
        self.assertIn("m.py:1", hits)
        listing = self.forge.call("list_dir", path=str(self.root))
        self.assertIn("m.py", listing)
        self.assertIn("n.txt", listing)

    def test_run_command_exit_and_output_and_env_scrub(self):
        out = self.forge.call(
            "run_command",
            command=f"{PY} -c \"print(40 + 2)\"",
            cwd=str(self.root))
        self.assertTrue(out.startswith("exit=0"), out)
        self.assertIn("42", out)
        os.environ["LEXIS_TEST_API_KEY"] = "leak-me-not"
        try:
            out = self.forge.call(
                "run_command",
                command=(f"{PY} -c \"import os; "
                         "print(os.environ.get("
                         "'LEXIS_TEST_API_KEY', 'ABSENT'))\""),
                cwd=str(self.root))
        finally:
            del os.environ["LEXIS_TEST_API_KEY"]
        self.assertIn("ABSENT", out)
        self.assertNotIn("leak-me-not", out)

    def test_run_tests_reports_suite_result(self):
        (self.root / "test_ok.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(2, 2)\n",
            encoding="utf-8")
        out = self.forge.call("run_tests", path=str(self.root))
        self.assertIn("exit=0", out)
        self.assertIn("OK", out)


class WebToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = (b"<html><head><title>T</title></head><body>"
                        b"<h1>Hello Web</h1>"
                        b'<a href="/next">Next page</a>'
                        b"</body></html>")
                if self.path == "/next":
                    body = b"<html><body>Second page body</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_fetch_returns_text_without_tags(self):
        out = Forge().call("fetch_url",
                           url=f"http://127.0.0.1:{self.port}/")
        self.assertIn("Hello Web", out)
        self.assertNotIn("<h1>", out)

    def test_browse_lists_links(self):
        out = Forge().call("browse_page",
                           url=f"http://127.0.0.1:{self.port}/")
        self.assertIn("Hello Web", out)
        self.assertIn("Next page", out)
        self.assertIn(f"http://127.0.0.1:{self.port}/next", out)


class WardenExecTest(unittest.TestCase):
    def test_exec_gate_matches_write_gate(self):
        self.assertEqual(ASK, Warden("EMBER").decide("exec"))
        self.assertEqual(ALLOW, Warden("INFERNO").decide("exec"))
        w = Warden("INFERNO")
        w.planning = True
        self.assertEqual(DENY, w.decide("exec"))


class MarkerParseTest(unittest.TestCase):
    def test_edit_marker(self):
        text = ("sure\n[EDIT_FILE: /tmp/a.py] x = 1 [WITH] x = 2 "
                "[/EDIT_FILE]")
        self.assertEqual(("/tmp/a.py", "x = 1", "x = 2"),
                         forge_mod.find_edit_marker(text))

    def test_line_marker_keeps_brackets_in_command(self):
        text = "[RUN: echo a[0] && echo done]\nnext"
        self.assertEqual("echo a[0] && echo done",
                         forge_mod.find_line_marker(text, "RUN"))


class PulseToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        while _OPEN_LEDGERS:
            _OPEN_LEDGERS.pop().close()
        self.tmp.cleanup()

    def test_catalog_injected_once_and_run_tool_loops(self):
        replies = iter([
            f"[RUN: {PY} -c \"print(6 * 7)\"]",
            "hasilnya 42",
            "baik",
        ])
        seen_messages = []

        def fake(model, messages, key):
            seen_messages.append(list(messages))
            yield next(replies)

        pulse, vault, old = make_pulse(self.root, fake)
        try:
            pulse.handle_turn("jalankan hitungan")
            pulse.handle_turn("lanjut")
        finally:
            bridge.stream_chat = old
        history = [m["content"] for m in vault.messages()]
        catalogs = [c for c in history if CATALOG_MARK in c]
        self.assertEqual(1, len(catalogs))
        feedback = [c for c in history if "[HASIL PERINTAH" in c]
        self.assertEqual(1, len(feedback))
        self.assertIn("42", feedback[0])
        self.assertIn("exit=0", feedback[0])

    def test_plan_mode_holds_run(self):
        marker_file = Path(self.root) / "should_not_exist.txt"
        replies = iter([
            f"[RUN: {PY} -c \"open(r'{marker_file}', 'w').close()\"]",
            "selesai",
        ])

        def fake(model, messages, key):
            yield next(replies)

        pulse, vault, old = make_pulse(self.root, fake)
        pulse.warden.planning = True
        try:
            pulse.handle_turn("buat file")
        finally:
            bridge.stream_chat = old
        self.assertFalse(marker_file.exists())

    def test_edit_tool_through_pulse(self):
        target = Path(self.root) / "cfg.py"
        target.write_text("LIMIT = 10\n", encoding="utf-8")
        replies = iter([
            f"[EDIT_FILE: {target}] LIMIT = 10 [WITH] LIMIT = 25 "
            "[/EDIT_FILE]",
            "sudah diganti",
        ])

        def fake(model, messages, key):
            yield next(replies)

        pulse, vault, old = make_pulse(self.root, fake)
        try:
            pulse.handle_turn("naikkan limit")
        finally:
            bridge.stream_chat = old
        self.assertEqual("LIMIT = 25\n",
                         target.read_text(encoding="utf-8"))


class ProtocolFilterTest(unittest.TestCase):
    def test_judge_visible_text_strips_new_markers(self):
        reply = "baik [RUN: echo hi] lanjut [EDIT_FILE: x] a [WITH] b"
        visible = judge_mod.visible_text(reply)
        self.assertNotIn("[RUN:", visible)
        self.assertNotIn("[EDIT_FILE:", visible)
        self.assertIn("baik", visible)


if __name__ == "__main__":
    unittest.main()
