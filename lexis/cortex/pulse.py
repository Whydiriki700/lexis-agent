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
                 on_first_token=None, on_event=None, should_stop=None) -> None:
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
        self.on_event = on_event
        self.should_stop = should_stop

    def _event(self, kind: str, data: dict) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def handle_turn(self, user_text: str) -> str:
        """Run one user turn. Returns 'done' or 'file_read', mirroring
        the original control flow (after a file read, the original
        waits for the next user input without storing the reply)."""
        self.vault.add("user", user_text)
        self.ledger.append_message(self.session_id, "user", user_text)
        started = time.time()
        self._event("turn_started", {"model": self.compass.current})
        api_key = bridge.current_key(self.root)

        full = ""
        think = ThinkFilter()
        first = True
        cancelled = False
        for delta in bridge.stream_chat(
            self.compass.current, self.vault.messages(), api_key
        ):
            if self.should_stop is not None and self.should_stop():
                cancelled = True
                break
            if first:
                self.on_first_token()
                first = False
            full += delta
            visible = think.feed(delta)
            if visible:
                self.emit_token(visible)
        self.emit_line("\n")

        if cancelled:
            self.vault.add("assistant", full)
            self.ledger.append_message(self.session_id, "assistant", full)
            self.ledger.append_event(self.session_id, "turn", "cancelled")
            self._event("turn_done", {
                "duration": time.time() - started, "outcome": "cancelled",
            })
            return "cancelled"

        read_path = forge_mod.find_read_marker(full)
        if read_path is not None:
            try:
                self._event("tool_start", {
                    "name": "read_file", "path": read_path,
                })
                t0 = time.time()
                content = self.forge.call("read_file", path=read_path)
                self._event("tool_end", {
                    "name": "read_file", "path": read_path, "ok": True,
                    "detail": f"{content.count(chr(10)) + 1} lines · "
                              f"{len(content.encode('utf-8'))} bytes",
                    "duration": time.time() - t0,
                })
                self.emit_line(f"  [SISTEM: Membaca file '{read_path}']")
                result_msg = f"[HASIL BACA FILE {read_path}]:\n{content}"
                self.vault.add("user", result_msg)
                self.ledger.append_message(self.session_id, "user", result_msg)
                self.emit_line("  [Lexis memproses isi file...]\n")
                self.ledger.append_event(
                    self.session_id, "tool", "read_file " + read_path
                )
                self._event("turn_done", {
                    "duration": time.time() - started, "outcome": "file_read",
                })
                return "file_read"
            except Exception as e:
                self._event("tool_end", {
                    "name": "read_file", "path": read_path, "ok": False,
                    "detail": str(e), "duration": 0.0,
                })
                self.emit_line(f"  [SISTEM ERROR: {e}]\n")

        write = forge_mod.find_write_marker(full)
        if write is not None:
            path, content = write
            try:
                self.emit_line(f"  [IZIN: Lexis ingin menulis file '{path}']")
                self._event("approval_needed", {
                    "name": "write_file", "path": path, "content": content,
                })
                decision = self.warden.decide(self.forge.risk_of("write_file"))
                allowed = False
                if decision == ALLOW:
                    allowed = True
                elif decision == ASK:
                    allowed = self.ask("  Izinkan? (y/n): ").lower() == "y"
                if allowed:
                    self._event("tool_start", {
                        "name": "write_file", "path": path, "content": content,
                    })
                    t0 = time.time()
                    self.forge.call("write_file", path=path, content=content)
                    self._event("tool_end", {
                        "name": "write_file", "path": path, "ok": True,
                        "detail": f"{len(content.encode('utf-8'))} bytes written",
                        "duration": time.time() - t0,
                    })
                    self.emit_line(f"  [SISTEM: File '{path}' ditulis!]\n")
                    self.ledger.append_event(
                        self.session_id, "tool", "write_file " + path
                    )
                else:
                    self._event("tool_end", {
                        "name": "write_file", "path": path, "ok": False,
                        "detail": "not approved", "duration": 0.0,
                    })
                    self.emit_line("  [SISTEM: Dibatalkan.]\n")
            except Exception as e:
                self.emit_line(f"  [SISTEM ERROR: {e}]\n")

        self.vault.add("assistant", full)
        self.ledger.append_message(self.session_id, "assistant", full)
        self.ledger.append_event(
            self.session_id, "turn",
            f"{self.compass.current} {time.time() - started:.2f}s",
        )
        self._event("turn_done", {
            "duration": time.time() - started, "outcome": "done",
        })
        return "done"
