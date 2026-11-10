# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Option B (Master, 2026-11-11): one path base for every
tool, the folder Lexis was launched from, never the profile
home. Writes, reads, edits, commands and tests all land in
the workdir; the profile home keeps only Lexis's own data.
Run from the project root:
python -m unittest tests.test_workdir -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexis.cortex import bridge  # noqa: E402
from lexis.cortex.compass import Compass  # noqa: E402
from lexis.cortex.forge import Forge  # noqa: E402
from lexis.cortex.ledger import Ledger  # noqa: E402
from lexis.cortex.pulse import Pulse  # noqa: E402
from lexis.cortex.vault import Vault  # noqa: E402
from lexis.cortex.warden import Warden  # noqa: E402


def scripted(replies):
    queue = list(replies)

    def stream(model, messages, key):
        yield queue.pop(0) if queue else "selesai."

    return stream


_OPEN_LEDGERS = []


def make(root, workdir, stream, events=None):
    ledger = Ledger(os.path.join(root, "state.db"))
    _OPEN_LEDGERS.append(ledger)
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])
    pulse = Pulse(
        root, Compass(), vault, Forge(), Warden("INFERNO"),
        ledger, sid,
        emit_token=lambda t: None, emit_line=lambda t: None,
        ask=lambda prompt: "y",
        workdir=workdir,
        on_event=(lambda k, d: events.append((k, d)))
        if events is not None else None,
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, vault, old


class WorkdirBaseTest(unittest.TestCase):
    def setUp(self):
        self.home_tmp = tempfile.TemporaryDirectory()
        self.work_tmp = tempfile.TemporaryDirectory()
        self.home = self.home_tmp.name
        self.work = self.work_tmp.name

    def tearDown(self):
        # Close ledgers before removing their folders: an
        # open state.db cannot be deleted on Windows.
        while _OPEN_LEDGERS:
            _OPEN_LEDGERS.pop().close()
        self.home_tmp.cleanup()
        self.work_tmp.cleanup()

    def test_abs_joins_workdir(self):
        pulse, _v, old = make(self.home, self.work,
                              scripted(["ok"]))
        try:
            self.assertEqual(
                pulse._abs("a/b.txt"),
                os.path.join(self.work, "a/b.txt"))
            self.assertEqual(
                pulse._abs(os.path.join(self.home, "x.txt")),
                os.path.join(self.home, "x.txt"))
        finally:
            bridge.stream_chat = old

    def test_write_lands_in_workdir_not_home(self):
        pulse, _v, old = make(
            self.home, self.work,
            scripted(["[WRITE_FILE: rel.txt]\nisi berkas\n"
                      "[/WRITE_FILE]", "selesai."]))
        try:
            pulse.handle_turn("tulis berkas")
        finally:
            bridge.stream_chat = old
        self.assertTrue(
            os.path.exists(os.path.join(self.work, "rel.txt")))
        self.assertFalse(
            os.path.exists(os.path.join(self.home, "rel.txt")))

    def test_read_resolves_in_workdir(self):
        Path(self.work, "data.txt").write_text(
            "isi-dari-workdir", encoding="utf-8")
        pulse, vault, old = make(
            self.home, self.work,
            scripted(["[READ_FILE: data.txt]", "selesai."]))
        try:
            pulse.handle_turn("baca berkas")
        finally:
            bridge.stream_chat = old
        joined = "\n".join(
            m["content"] for m in vault.messages())
        self.assertIn("isi-dari-workdir", joined)

    def test_command_output_streams_as_events(self):
        events = []
        inner = f'"{sys.executable}" -c'
        pulse, _v, old = make(
            self.home, self.work,
            scripted([f"[RUN: {inner} \"print('baris-satu');"
                       "print('baris-dua')\"]", "selesai."]),
            events=events)
        try:
            pulse.handle_turn("jalankan")
        finally:
            bridge.stream_chat = old
        streamed = [d["text"] for k, d in events
                    if k == "tool_output"]
        self.assertIn("baris-satu", streamed)
        self.assertIn("baris-dua", streamed)
        self.assertLess(streamed.index("baris-satu"),
                        streamed.index("baris-dua"))

    def test_command_runs_in_workdir(self):
        inner = f'"{sys.executable}" -c'
        pulse, _v, old = make(
            self.home, self.work,
            scripted([f"[RUN: {inner} \"open('cmd.txt','w')"
                       ".write('ok')\"]", "selesai."]))
        try:
            pulse.handle_turn("jalankan")
        finally:
            bridge.stream_chat = old
        self.assertTrue(
            os.path.exists(os.path.join(self.work, "cmd.txt")))
        self.assertFalse(
            os.path.exists(os.path.join(self.home, "cmd.txt")))


if __name__ == "__main__":
    unittest.main()
