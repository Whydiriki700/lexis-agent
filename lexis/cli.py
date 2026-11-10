# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Plain CLI surface for Lexis (Fase 1).

Behavior mirrors the original main.py exactly: same header, same
prompts, same /model flow, same spinner. The only additions are
invisible by default: sessions are journaled to lexis_data/state.db
and `--resume` restores the last session. The Visor (Textual) surface
replaces this face in Fase 2 without touching the Cortex.
"""

import os
import sys
import threading
import time

from lexis.cortex import bridge
from lexis.cortex.compass import MODELS, Compass
from lexis.cortex.forge import Forge
from lexis.cortex.ledger import Ledger
from lexis.cortex.pulse import Pulse
from lexis.cortex.vault import Vault
from lexis.cortex.warden import Warden

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Spinner:
    """The original | / - \\ waiting spinner, as a stoppable thread."""

    _CHARS = ["|", "/", "-", "\\"]

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        idx = 0
        while not self._stop.is_set():
            sys.stdout.write(f"\r{self._CHARS[idx % 4]}")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv or "-V" in argv:
        import lexis

        print(f"Lexis Agent {lexis.__version__}")
        return 0
    if argv and argv[0] == "doctor":
        from lexis import doctor

        return doctor.run()
    if argv and argv[0] == "visor":
        from lexis.visor.app import run_visor

        return run_visor(argv[1:])
    interactive = (
        "--interactive" in argv or "-i" in argv or sys.stdin.isatty()
    )
    if not interactive:
        import lexis

        print(f"Lexis Agent {lexis.__version__}")
        print("Run Lexis in a terminal to start chatting,")
        print("or use: lexis doctor | lexis --version | lexis --resume")
        return 0
    bridge.load_env(ROOT)
    compass = Compass()
    warden = Warden(os.getenv("LEXIS_MODE", "EMBER"))
    forge = Forge()
    data_dir = os.path.join(ROOT, "lexis_data")
    os.makedirs(data_dir, exist_ok=True)
    ledger = Ledger(os.path.join(data_dir, "state.db"))
    vault = Vault()

    session_id = None
    if "--resume" in argv:
        last = ledger.last_session_id()
        if last is not None:
            session_id = last
            vault.replace_all(ledger.load_messages(session_id))
    if session_id is None:
        session_id = ledger.start_session(compass.current)
        for m in vault.bootstrap():
            ledger.append_message(session_id, m["role"], m["content"])
    vault.register_config(ROOT, ledger)

    spinner = Spinner()

    def on_first_token() -> None:
        spinner.stop()
        print("Lexis: ", end="", flush=True)

    pulse = Pulse(
        ROOT, compass, vault, forge, warden, ledger, session_id,
        emit_token=lambda t: print(t, end="", flush=True),
        emit_line=lambda t: print(t),
        ask=lambda prompt: input(prompt),
        on_first_token=on_first_token,
    )

    print("=== LEXIS (HUMAN MODE) ===")
    print("Ketik 'exit' untuk keluar.\n")

    while True:
        try:
            user_input = input("Kamu: ")
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue
            low = user_input.strip().lower()
            if low == "/model":
                print("\nModel tersedia:")
                for i, m in enumerate(MODELS, 1):
                    mark = " (aktif)" if m == compass.current else ""
                    print(f"  {i}. {m}{mark}")
                pilih = input("Pilih nomor atau nama model: ").strip()
                if not compass.select(pilih):
                    print("[Model tidak ditemukan, tetap pakai yang aktif]")
                print(f"[Model aktif: {compass.current}]\n")
                continue
            if low.startswith("/model "):
                m = user_input.strip()[7:].strip()
                if m in MODELS:
                    compass.current = m
                    print(f"[Model aktif: {compass.current}]\n")
                else:
                    print("[Model tidak ditemukan]\n")
                continue
            spinner.start()
            try:
                pulse.handle_turn(user_input)
            finally:
                spinner.stop()
        except KeyboardInterrupt:
            spinner.stop()
            print("\nSampai jumpa, sayang.")
            break
        except EOFError:
            spinner.stop()
            break
        except Exception as e:
            spinner.stop()
            print(f"\n[Error]: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
