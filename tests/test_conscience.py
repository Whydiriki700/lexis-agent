"""Conscience: EMBER's deliberation gate (Master's order
2026-11-11 to build items 1-5; blueprint: EMBER may hold
and refuse what it judges destructive, and must explain).

The refusal is narrow by design: Lexis's own configuration
layer, credential and trust files, memory store, and
machine-wiping commands. Ordinary work is never refused,
and BLAZE/INFERNO never refuse at all.
"""

import os
import tempfile
import unittest

from lexis.cortex import bridge, conscience
from lexis.cortex.compass import Compass
from lexis.cortex.forge import Forge
from lexis.cortex.ledger import Ledger
from lexis.cortex.pulse import Pulse
from lexis.cortex.vault import Vault
from lexis.cortex.warden import Warden


class DeliberateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def d(self, name, primary, mode="EMBER"):
        return conscience.deliberate(
            name, primary, mode, self.root, self.root)

    def test_config_layer_is_refused(self):
        target = os.path.join(self.root, "config", "PROTOCOL.md")
        self.assertIn("configuration", self.d("write_file", target))
        self.assertIn("configuration", self.d("edit_file", target))

    def test_credential_and_trust_files_are_refused(self):
        for rel in (".env", "providers.json", "visor_prefs.json"):
            self.assertIsNotNone(
                self.d("write_file", os.path.join(self.root, rel)),
                rel)

    def test_memory_store_and_pins_are_refused(self):
        self.assertIn(
            "memory store",
            self.d("write_file", os.path.join(
                self.root, "lexis_data", "state.db")))
        self.assertIsNotNone(
            self.d("write_file", os.path.join(
                self.root, "skills", ".pins.json")))

    def test_ordinary_work_is_not_refused(self):
        self.assertIsNone(self.d("write_file", "notes.txt"))
        self.assertIsNone(self.d(
            "write_file", os.path.join(self.root, "src", "app.py")))
        self.assertIsNone(self.d("run_command", "echo hello"))
        self.assertIsNone(self.d("run_command", "rm -rf build"))
        self.assertIsNone(self.d("read_file", ".env"))

    def test_catastrophic_commands_are_refused(self):
        self.assertIsNotNone(self.d("run_command", "format C:"))
        self.assertIsNotNone(self.d("run_command", "rm -rf /"))
        self.assertIsNotNone(
            self.d("run_command", "del /s /q C:\\"))
        self.assertIsNotNone(self.d(
            "run_command",
            f'del "{self.root}\\lexis_data\\state.db"'))
        self.assertIsNotNone(self.d(
            "run_command", f'rd /s /q "{self.root}"'))

    def test_other_modes_never_refuse(self):
        target = os.path.join(self.root, "config", "PROTOCOL.md")
        for mode in ("BLAZE", "INFERNO"):
            self.assertIsNone(self.d("write_file", target, mode))
            self.assertIsNone(
                self.d("run_command", "format C:", mode))


def make_pulse(root, stream, mode):
    ledger = Ledger(os.path.join(root, "state.db"))
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])
    pulse = Pulse(
        root, Compass(), vault, Forge(), Warden(mode), ledger,
        sid, workdir=root,
        emit_token=lambda token: None,
        emit_line=lambda line: None,
        ask=lambda prompt: "y",
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, vault, ledger, old


class ConsciencePulseTest(unittest.TestCase):
    """The same instruction, two modes: EMBER refuses even
    though the owner would have approved; BLAZE obeys."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "config"))
        self.target = os.path.join(
            self.root, "config", "PROTOCOL.md")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, mode):
        replies = iter([
            f"[WRITE_FILE: {self.target}] changed "
            f"[/WRITE_FILE]",
            "baik",
        ])

        def fake(model, messages, key):
            yield next(replies)

        pulse, vault, ledger, old = make_pulse(
            self.root, fake, mode)
        try:
            pulse.handle_turn("ubah protokolnya")
        finally:
            bridge.stream_chat = old
        history = [m["content"] for m in vault.messages()]
        events = ledger.events(pulse.session_id, kind="conscience")
        ledger.close()
        return history, events

    def test_ember_refuses_and_explains(self):
        history, events = self._run("EMBER")
        self.assertFalse(os.path.exists(self.target))
        told = [c for c in history if "DITOLAK OLEH LEXIS" in c]
        self.assertEqual(1, len(told))
        self.assertIn("configuration", told[0])
        self.assertEqual(1, len(events))

    def test_blaze_obeys(self):
        history, events = self._run("BLAZE")
        self.assertTrue(os.path.exists(self.target))
        self.assertEqual(0, len(events))


if __name__ == "__main__":
    unittest.main()
