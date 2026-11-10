# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Pulse: the agent loop.

Fase 1 reproduces the original main.py turn semantics exactly, split
behind a small interface: stream the reply, filter thinking tags,
then run the file tools found in the reply. The surface (CLI, Visor)
injects how tokens are shown, how lines are printed, and how
permission questions are asked, so the loop is testable headlessly.

Fase 3 keeps those semantics and adds the Cortex behaviour around
them: owner statements are lifted into cold-tier facts, the context
is compacted by prism at the budget trigger, a turn falls back along
the compass chain when a model errors or answers empty (only before
any token reaches the user, so a reply is never doubled), every
finished turn is judged and costed into the ledger, and plan mode
drafts under a tool-level write ban, then executes step by step.
"""

import hashlib
import json
import re
import time

from . import bridge
from . import forge as forge_mod
from . import judge as judge_mod
from . import prism
from .warden import ALLOW, ASK, DENY


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


_STEP_MARK = re.compile(r"^[-*•]\s*|^\d+[.)]\s*")


def parse_plan(reply: str, goal: str):
    """Pull plan steps out of a model reply: one step per line,
    bullets and numbering stripped. Falls back to the goal itself as
    a single step when fewer than two step-shaped lines are found:
    a lone line is prose, not a plan."""
    steps = []
    for line in (reply or "").splitlines():
        s = _STEP_MARK.sub("", line.strip()).strip()
        if "WRITE_FILE" in s or "READ_FILE" in s:
            continue  # tool protocol lines are not plan steps
        if 3 <= len(s) <= 140 and not s.endswith(":"):
            steps.append(s)
        if len(steps) >= 12:
            break
    if len(steps) < 2:
        return [goal]
    return steps


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
        self.plan = []
        self.plan_goal = ""
        self._turn_tools = []
        self._written_sigs = set()

    def _event(self, kind: str, data: dict) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _finish(self, outcome, started, model_used, prompt_tokens, full):
        """Judge and cost every finished turn into the ledger."""
        duration = time.time() - started
        if outcome in ("done", "file_read", "write_done"):
            verdict = judge_mod.verify_turn(full, self._turn_tools, self.root)
            self.ledger.append_event(
                self.session_id, "judge",
                f"{verdict.status}: " + "; ".join(verdict.reasons),
            )
            self._event("judge_verdict", {
                "status": verdict.status, "reasons": verdict.reasons,
            })
        self.ledger.record_cost(
            self.session_id, model_used, duration,
            prompt_tokens, len(full) // 4, outcome,
        )
        self._event("turn_done", {
            "duration": duration, "outcome": outcome,
        })

    def _do_write(self, path: str, content: str) -> str:
        """Execute one write marker through the warden and, in ASK
        modes, the owner. Returns 'written', or 'stopped' when the
        write was held, declined, or failed (the turn then ends,
        as the original ended it after a write decision)."""
        try:
            self.emit_line(f"  [IZIN: Lexis ingin menulis file '{path}']")
            self._event("approval_needed", {
                "name": "write_file", "path": path, "content": content,
            })
            decision = self.warden.decide(self.forge.risk_of("write_file"))
            if decision == DENY:
                self._event("tool_end", {
                    "name": "write_file", "path": path, "ok": False,
                    "detail": "held by plan mode", "duration": 0.0,
                })
                self._turn_tools.append({
                    "name": "write_file", "ok": False, "path": path,
                    "detail": "held by plan mode",
                })
                self.emit_line(
                    "  [SISTEM: Mode rencana aktif: penulisan ditahan.]\n"
                )
                return "stopped"
            allowed = False
            if decision == ALLOW:
                allowed = True
            elif decision == ASK:
                allowed = self.ask("  Izinkan? (y/n): ").lower() == "y"
            if not allowed:
                self._event("tool_end", {
                    "name": "write_file", "path": path, "ok": False,
                    "detail": "not approved", "duration": 0.0,
                })
                self._turn_tools.append({
                    "name": "write_file", "ok": False, "path": path,
                    "detail": "not approved",
                })
                self.emit_line("  [SISTEM: Dibatalkan.]\n")
                return "stopped"
            self._event("tool_start", {
                "name": "write_file", "path": path,
                "content": content,
            })
            t0 = time.time()
            self.forge.call("write_file", path=path, content=content)
            detail = f"{len(content.encode('utf-8'))} bytes written"
            self._event("tool_end", {
                "name": "write_file", "path": path, "ok": True,
                "detail": detail, "duration": time.time() - t0,
            })
            self._turn_tools.append({
                "name": "write_file", "ok": True, "path": path,
                "content": content, "detail": detail,
            })
            self.emit_line(f"  [SISTEM: File '{path}' ditulis!]\n")
            self.ledger.append_event(
                self.session_id, "tool", "write_file " + path
            )
            return "written"
        except Exception as e:
            self.emit_line(f"  [SISTEM ERROR: {e}]\n")
            return "stopped"

    def handle_turn(self, user_text: str) -> str:
        """Run one user turn as a completion loop: a file read or a
        successful write does not end the turn. The result is fed
        back and the model is called again inside the same turn,
        without storing the marker reply and without waiting for
        the user, until the model answers without file markers.
        (The original looped reads this way but ended the turn
        after one write; the loop now covers writes too, so one
        instruction can finish a multi-file task. Every write
        still passes the warden and, in EMBER, the owner.)"""
        self.vault.add("user", user_text)
        self.ledger.append_message(self.session_id, "user", user_text)
        learned = self.vault.learn_from(self.ledger, self.session_id, user_text)
        if learned:
            self.ledger.append_event(
                self.session_id, "facts", f"{learned} stored"
            )
        if prism.needs_compaction(self.vault.messages()):
            report = prism.compact(self.vault, self.ledger, self.session_id)
            if report:
                self._event("compaction", report)
        self._written_sigs = set()
        actions = 0
        while True:
            outcome = self._turn_once(user_text)
            if outcome not in ("file_read", "write_done"):
                return outcome
            actions += 1
            if actions >= 25:
                # Safety valve: the original looped reads without a
                # cap; 25 consecutive tool actions in one turn is a
                # runaway, so the turn ends with what it has.
                return "done"

    def _turn_once(self, user_text: str) -> str:
        """One model call plus its marker handling. Returns 'done',
        'file_read', 'write_done', or 'cancelled'."""
        self._turn_tools = []
        started = time.time()
        messages = self.vault.messages()
        prompt_tokens = prism.estimate_tokens(messages)
        model_used = self.compass.route(user_text)
        self._event("turn_started", {"model": model_used})
        api_key = bridge.current_key(self.root)

        full = ""
        got_any = False
        cancelled = False
        chain = self.compass.chain(model_used)
        for attempt_no, model in enumerate(chain):
            model_used = model
            think = ThinkFilter()
            attempt_full = ""
            attempt_got = False
            try:
                for delta in bridge.stream_chat(model, messages, api_key):
                    if self.should_stop is not None and self.should_stop():
                        cancelled = True
                        break
                    if not attempt_got and not got_any:
                        self.on_first_token()
                    attempt_got = True
                    attempt_full += delta
                    visible = think.feed(delta)
                    if visible:
                        self.emit_token(visible)
            except Exception:
                if attempt_got:
                    # A partial reply is already on screen: it stands.
                    full = attempt_full
                    got_any = True
                    break
                if attempt_no + 1 < len(chain):
                    self._event("model_fallback", {
                        "from": model, "to": chain[attempt_no + 1],
                        "reason": "model error",
                    })
                    continue
                raise
            full = attempt_full
            got_any = attempt_got
            if cancelled or got_any:
                break
            if attempt_no + 1 < len(chain):
                self._event("model_fallback", {
                    "from": model, "to": chain[attempt_no + 1],
                    "reason": "empty reply",
                })
                continue
            break
        self.emit_line("\n")

        if cancelled:
            self.vault.add("assistant", full)
            self.ledger.append_message(self.session_id, "assistant", full)
            self.ledger.append_event(self.session_id, "turn", "cancelled")
            self._finish("cancelled", started, model_used, prompt_tokens, full)
            return "cancelled"

        read_path = forge_mod.find_read_marker(full)
        if read_path is not None:
            try:
                self._event("tool_start", {
                    "name": "read_file", "path": read_path,
                })
                t0 = time.time()
                content = self.forge.call("read_file", path=read_path)
                detail = (f"{content.count(chr(10)) + 1} lines · "
                          f"{len(content.encode('utf-8'))} bytes")
                self._event("tool_end", {
                    "name": "read_file", "path": read_path, "ok": True,
                    "detail": detail, "duration": time.time() - t0,
                })
                self._turn_tools.append({
                    "name": "read_file", "ok": True, "path": read_path,
                    "detail": detail,
                })
                self.emit_line(f"  [SISTEM: Membaca file '{read_path}']")
                result_msg = f"[HASIL BACA FILE {read_path}]:\n{content}"
                self.vault.add("user", result_msg)
                self.ledger.append_message(self.session_id, "user", result_msg)
                self.emit_line("  [Lexis memproses isi file...]\n")
                self.ledger.append_event(
                    self.session_id, "tool", "read_file " + read_path
                )
                self._finish("file_read", started, model_used,
                             prompt_tokens, full)
                return "file_read"
            except Exception as e:
                self._event("tool_end", {
                    "name": "read_file", "path": read_path, "ok": False,
                    "detail": str(e), "duration": 0.0,
                })
                self._turn_tools.append({
                    "name": "read_file", "ok": False, "path": read_path,
                    "detail": str(e),
                })
                self.emit_line(f"  [SISTEM ERROR: {e}]\n")

        markers = forge_mod.find_write_markers(full)
        if markers:
            written = []
            stopped = False
            for path, content in markers:
                sig = hashlib.sha256(
                    (path + "\n" + content).encode("utf-8")
                ).hexdigest()
                if sig in self._written_sigs:
                    self.emit_line(
                        f"  [SISTEM: '{path}' sudah ditulis, dilewati.]\n"
                    )
                    continue
                if self._do_write(path, content) == "written":
                    self._written_sigs.add(sig)
                    written.append(path)
                else:
                    stopped = True
                    break
            if written and not stopped:
                names = ", ".join(written)
                result_msg = (
                    f"[HASIL TULIS FILE {names}]: berhasil ditulis. "
                    "Lanjutkan tugas sampai selesai. Jangan menulis "
                    "ulang berkas yang sudah ditulis; kalau tugas "
                    "sudah selesai, jawab dengan teks biasa tanpa "
                    "penanda berkas."
                )
                self.vault.add("user", result_msg)
                self.ledger.append_message(
                    self.session_id, "user", result_msg
                )
                self.emit_line("  [Lexis melanjutkan...]\n")
                self._finish("write_done", started, model_used,
                             prompt_tokens, full)
                return "write_done"
            # Stopped by a decision, or every marker duplicated
            # work already done this turn: the turn ends below
            # with the reply stored, like a finished turn.

        self.vault.add("assistant", full)
        self.ledger.append_message(self.session_id, "assistant", full)
        self.ledger.append_event(
            self.session_id, "turn",
            f"{model_used} {time.time() - started:.2f}s",
        )
        self._finish("done", started, model_used, prompt_tokens, full)
        return "done"

    # --- Fase 3: plan mode --------------------------------------------

    def draft_plan(self, goal: str):
        """Draft a plan for the goal under the tool-level write ban.
        The drafting turn is a normal turn (it is judged and costed);
        only its writes are held. Returns the list of step labels."""
        request = (
            "Plan this task step by step. Reply with the steps only, "
            "one step per line, no file changes.\nTask: " + goal
        )
        self.warden.planning = True
        try:
            self.handle_turn(request)
        finally:
            self.warden.planning = False
        reply = ""
        for m in reversed(self.vault.messages()):
            if m.get("role") == "assistant":
                reply = m.get("content", "")
                break
        steps = parse_plan(reply, goal)
        self.plan = [{"label": s, "state": "todo"} for s in steps]
        self.plan_goal = goal
        self.ledger.append_event(
            self.session_id, "plan",
            json.dumps({"goal": goal, "steps": steps}),
        )
        self._event("plan_ready", {"goal": goal, "steps": steps})
        return steps

    def run_plan(self) -> str:
        """Execute the drafted plan step by step as normal turns.
        Returns 'done', 'cancelled', or 'empty' (no plan drafted)."""
        if not self.plan:
            return "empty"
        for step in self.plan:
            if step["state"] == "done":
                continue
            step["state"] = "now"
            self._event("plan_step", {
                "label": step["label"], "state": "now",
            })
            outcome = self.handle_turn(step["label"])
            if outcome == "cancelled":
                step["state"] = "todo"
                self._event("plan_step", {
                    "label": step["label"], "state": "todo",
                })
                return "cancelled"
            step["state"] = "done"
            self._event("plan_step", {
                "label": step["label"], "state": "done",
            })
        self._event("plan_done", {"goal": self.plan_goal})
        return "done"
