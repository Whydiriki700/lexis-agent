# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The phase contract (inter-tab discussion, 2026-11-10):
Pulse emits the work phase as data, one event per transition,
and the Visor renders what it receives. These tests pin the
exact sequence of one plain turn and one approved write turn.
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
from lexis.cortex.pulse import PHASES, Pulse  # noqa: E402
from lexis.cortex.vault import Vault  # noqa: E402
from lexis.cortex.warden import Warden  # noqa: E402


def make_pulse(root, stream, mode="INFERNO", ask=None):
    ledger = Ledger(os.path.join(root, "state.db"))
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])
    phases = []
    pulse = Pulse(
        root, Compass(), vault, Forge(), Warden(mode), ledger, sid,
        workdir=root,
        emit_token=lambda t: None, emit_line=lambda t: None,
        ask=ask or (lambda prompt: "y"),
        on_event=lambda kind, data: phases.append(data["phase"])
        if kind == "phase" else None,
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, ledger, phases, old


class PhaseContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self):
        bridge.stream_chat = getattr(self, "_old", bridge.stream_chat)

    def run_pulse(self, stream, mode="INFERNO", ask=None):
        pulse, ledger, phases, old = make_pulse(
            self.tmp, stream, mode, ask)
        self._old = old
        self.addCleanup(ledger.close)
        return pulse, phases

    def test_contract_names(self):
        self.assertEqual(
            ("low-idle", "thinking", "typing", "working",
             "held-for-approval", "dimming"),
            PHASES,
        )

    def test_plain_turn_sequence(self):
        def stream(model, messages, key):
            yield "Halo dunia."

        pulse, phases = self.run_pulse(stream)
        self.assertEqual("low-idle", pulse.phase)
        pulse.handle_turn("halo")
        self.assertEqual(
            ["thinking", "typing", "dimming"], phases)
        self.assertEqual("dimming", pulse.phase)

    def test_approved_write_turn_sequence(self):
        calls = {"n": 0}

        def stream(model, messages, key):
            calls["n"] += 1
            if calls["n"] == 1:
                yield ("Siap.\n[WRITE_FILE: note.txt]\n"
                       "isi catatan\n[/WRITE_FILE]")
            else:
                yield "Selesai."

        pulse, phases = self.run_pulse(stream, mode="EMBER")
        pulse.handle_turn("tulis catatan")
        self.assertEqual(
            ["thinking", "typing", "held-for-approval",
             "working", "thinking", "typing", "dimming"],
            phases,
        )
        self.assertTrue(
            os.path.isfile(os.path.join(self.tmp, "note.txt")))


class VisorPhaseRenderTest(unittest.IsolatedAsyncioTestCase):
    async def test_visor_consumes_the_phase_event(self):
        from lexis.visor.app import LexisVisor

        old = bridge.stream_chat

        def stream(model, messages, key):
            yield "Halo dari fase."

        bridge.stream_chat = stream
        try:
            with tempfile.TemporaryDirectory() as d:
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("halo")
                    for _ in range(60):
                        await pilot.pause()
                        if not app.busy:
                            break
                    self.assertEqual("dimming", app._pulse_phase)
        finally:
            bridge.stream_chat = old


if __name__ == "__main__":
    unittest.main()
