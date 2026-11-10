# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Pulse: the agent loop.

Fase 1 reproduces the original main.py turn semantics exactly, split
behind a small interface: stream the reply, filter thinking tags,
then run the file tools found in the reply. The surface (CLI, later
Visor) injects how tokens are shown, how lines are printed, and how
permission questions are asked, so the loop is testable headlessly.
"""

import time

from . import bridge
from . import forge as forge_mod
from .warden import ALLOW, ASK


class ThinkFilter:
    """The original buffer-based <thinking> filter, semantics preserved
    (including its known quirk: visible text sharing a chunk with an
    opening tag is dropped, exactly as the original dropped it)."""

    def __init__(self) -> None:
        self.buffer = ""
        self.is_thinking = False

    def feed(self, content: str) -> str:
        self.buffer += content
        if "<thinking>" in self.buffer:
            self.is_thinking = True
            self.buffer = self.buffer.split("<thinking>")[-1]
        if "</thinking>" in self.buffer:
            self.is_thinking = False
            self.buffer = self.buffer.split("</thinking>")[-1]
        if not self.is_thinking and self.buffer:
            out = self.buffer
            self.buffer = ""
            return out
        return ""


class Pulse:
    def __init__(self, root, compass, vault, forge, warden, ledger,
                 session_id, emit_token, emit_line, ask,
                 on_first_token=None) -> None:
        self.root = root
        self.compass = compass
        self.vault = vault
        self.forge = forge
        self.warden = warden
        self.ledger = ledger
        self.session_id = session_id
        self.emit_token = emit_token
        self.emit_line = emit_line
        self.ask = ask
        self.on_first_token = on_first_token or (lambda: None)

    def handle_turn(self, user_text: str) -> str:
        """Run one user turn. Returns 'done' or 'file_read', mirroring
        the original control flow (after a file read, the original
        waits for the next user input without storing the reply)."""
        self.vault.add("user", user_text)
        self.ledger.append_message(self.session_id, "user", user_text)
        started = time.time()
        api_key = bridge.current_key(self.root)

        full = ""
        think = ThinkFilter()
        first = True
        for delta in bridge.stream_chat(
            self.compass.current, self.vault.messages(), api_key
        ):
            if first:
                self.on_first_token()
                first = False
            full += delta
            visible = think.feed(delta)
            if visible:
                self.emit_token(visible)
        self.emit_line("\n")

        read_path = forge_mod.find_read_marker(full)
        if read_path is not None:
            try:
                content = self.forge.call("read_file", path=read_path)
                self.emit_line(f"  [SISTEM: Membaca file '{read_path}']")
                result_msg = f"[HASIL BACA FILE {read_path}]:\n{content}"
                self.vault.add("user", result_msg)
                self.ledger.append_message(self.session_id, "user", result_msg)
                self.emit_line("  [Lexis memproses isi file...]\n")
                self.ledger.append_event(
                    self.session_id, "tool", "read_file " + read_path
                )
                return "file_read"
            except Exception as e:
                self.emit_line(f"  [SISTEM ERROR: {e}]\n")

        write = forge_mod.find_write_marker(full)
        if write is not None:
            path, content = write
            try:
                self.emit_line(f"  [IZIN: Lexis ingin menulis file '{path}']")
                decision = self.warden.decide(self.forge.risk_of("write_file"))
                allowed = False
                if decision == ALLOW:
                    allowed = True
                elif decision == ASK:
                    allowed = self.ask("  Izinkan? (y/n): ").lower() == "y"
                if allowed:
                    self.forge.call("write_file", path=path, content=content)
                    self.emit_line(f"  [SISTEM: File '{path}' ditulis!]\n")
                    self.ledger.append_event(
                        self.session_id, "tool", "write_file " + path
                    )
                else:
                    self.emit_line("  [SISTEM: Dibatalkan.]\n")
            except Exception as e:
                self.emit_line(f"  [SISTEM ERROR: {e}]\n")

        self.vault.add("assistant", full)
        self.ledger.append_message(self.session_id, "assistant", full)
        self.ledger.append_event(
            self.session_id, "turn",
            f"{self.compass.current} {time.time() - started:.2f}s",
        )
        return "done"
