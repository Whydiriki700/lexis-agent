# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The three compliance modes as proven behavior, not product
copy (Master, 2026-11-11).

- EMBER asks every time.
- BLAZE warns once per risk class, then the owner's word
  stands for the rest of the session.
- INFERNO never asks.
Plan drafting still denies writes and execution in all modes.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexis.cortex import bridge  # noqa: E402
from lexis.cortex.compass import Compass  # noqa: E402
from lexis.cortex.forge import Forge  # noqa: E402
from lexis.cortex.ledger import Ledger  # noqa: E402
from lexis.cortex.pulse import Pulse  # noqa: E402
from lexis.cortex.vault import Vault  # noqa: E402
from lexis.cortex.warden import ALLOW, ASK, DENY, WARN, Warden  # noqa: E402


class WardenSemanticsTest(unittest.TestCase):
    def test_blaze_warns_once_per_risk_class(self):
        w = Warden("BLAZE")
        self.assertEqual(WARN, w.decide("write"))
        self.assertEqual(WARN, w.decide("exec"))
        w.note_warned("write")
        self.assertEqual(ALLOW, w.decide("write"))
        self.assertEqual(WARN, w.decide("exec"))

    def test_ember_asks_every_time(self):
        w = Warden("EMBER")
        self.assertEqual(ASK, w.decide("write"))
        w.note_warned("write")
        self.assertEqual(ASK, w.decide("write"))

    def test_mode_switch_resets_blaze_memory(self):
        w = Warden("BLAZE")
        w.note_warned("write")
        self.assertEqual(ALLOW, w.decide("write"))
        w.set_mode("EMBER")
        w.set_mode("BLAZE")
        self.assertEqual(WARN, w.decide("write"))

    def test_plan_denies_before_any_mode_behavior(self):
        for mode in ("EMBER", "BLAZE", "INFERNO"):
            w = Warden(mode)
            w.planning = True
            self.assertEqual(DENY, w.decide("write"))
            self.assertEqual(DENY, w.decide("exec"))

    def test_reads_never_gated(self):
        for mode in ("EMBER", "BLAZE", "INFERNO"):
            self.assertEqual(ALLOW, Warden(mode).decide("read"))


def make_pulse(root, stream, mode, asks, events=None):
    ledger = Ledger(os.path.join(root, "state.db"))
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])

    def ask(prompt):
        asks.append(prompt)
        return "y"

    pulse = Pulse(
        root, Compass(), vault, Forge(), Warden(mode), ledger, sid,
        workdir=root,
        emit_token=lambda t: None,
        emit_line=lambda t: None,
        ask=ask,
        on_event=(lambda k, d: events.append((k, d)))
        if events is not None else None,
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, ledger, old


def two_write_stream(a, b):
    calls = []

    def fake(model, messages, key):
        calls.append(1)
        if len(calls) == 1:
            yield (f"[WRITE_FILE: {a}]print('a')\n[/WRITE_FILE]\n"
                   f"[WRITE_FILE: {b}]print('b')\n[/WRITE_FILE]")
        else:
            yield "both files written"

    return fake


class PulseModeProofTest(unittest.TestCase):
    def run_mode(self, mode):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        a = os.path.join(tmp, "a.py")
        b = os.path.join(tmp, "b.py")
        asks, events = [], []
        pulse, ledger, old = make_pulse(
            tmp, two_write_stream(a, b), mode, asks, events)
        self.addCleanup(ledger.close)
        try:
            self.assertEqual(pulse.handle_turn("write both"), "done")
        finally:
            bridge.stream_chat = old
        self.assertTrue(os.path.isfile(a), f"{mode}: a.py missing")
        self.assertTrue(os.path.isfile(b), f"{mode}: b.py missing")
        return asks, events

    def test_ember_asks_for_every_write(self):
        asks, _ = self.run_mode("EMBER")
        self.assertEqual(2, len(asks))

    def test_blaze_warns_once_then_stands(self):
        asks, events = self.run_mode("BLAZE")
        self.assertEqual(1, len(asks))
        self.assertIn("Peringatan BLAZE", asks[0])
        warned = [d for k, d in events
                  if k == "approval_needed" and d.get("warn_once")]
        self.assertEqual(1, len(warned))

    def test_inferno_never_asks(self):
        asks, _ = self.run_mode("INFERNO")
        self.assertEqual(0, len(asks))


if __name__ == "__main__":
    unittest.main()
