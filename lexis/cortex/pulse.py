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
import os
import re
import time

from . import bridge
from . import conscience as conscience_mod
from . import forge as forge_mod
from . import judge as judge_mod
from . import prism
from .warden import ALLOW, ASK, DENY, WARN

# The phase contract (inter-tab discussion, 2026-11-10): the
# agent's work phase is DATA, emitted by Pulse as a "phase"
# event on every transition. Surfaces render the phase; they
# never derive it locally. A session rests at low-idle, a turn
# moves thinking -> typing, tools run under working, an owner
# question holds the turn at held-for-approval, and every
# finished turn settles through dimming.
PHASES = (
    "low-idle", "thinking", "typing", "working",
    "held-for-approval", "dimming",
)

CATALOG_MARK = "[SISTEM: Tool tambahan Lexis."

CATALOG_TEXT = (
    CATALOG_MARK + " Selain membaca dan menulis file, kamu punya "
    "tool berikut. Pakai persis format penandanya, satu tool dalam "
    "satu balasan, dan hasil tool kembali sebagai pesan [HASIL ...]:\n"
    "[EDIT_FILE: path] teks lama [WITH] teks baru [/EDIT_FILE] "
    "mengganti satu potongan file secara persis; teks lama harus "
    "muncul tepat satu kali di file itu.\n"
    "[SEARCH: pola :: folder] mencari pola di semua file teks "
    "dalam folder; folder \".\" berarti folder kerja.\n"
    "[LIST_DIR: path] melihat isi sebuah folder.\n"
    "[RUN: perintah] menjalankan perintah terminal di folder "
    "kerja, batas 60 detik; hasilnya berisi exit code dan output.\n"
    "[RUN_TESTS: path] menjalankan rangkaian tes di folder itu.\n"
    "[FETCH: url] mengambil isi halaman web sebagai teks.\n"
    "[BROWSE: url] membuka halaman web beserta daftar tautan "
    "bernomor untuk diikuti dengan FETCH atau BROWSE berikutnya.\n"
    "Selesaikan tugas sampai tuntas dengan tool ini. Jangan "
    "mengklaim hasil perintah atau tes tanpa menjalankannya.]"
)


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
                 on_first_token=None, on_event=None, should_stop=None,
                 workdir=None) -> None:
        self.root = root
        # Option B (Master, 2026-11-11): every tool path and
        # command resolves against the folder Lexis was
        # launched from, like any coding agent. The profile
        # home (root) keeps only Lexis's own data: ledger,
        # skills, providers, keys.
        self.workdir = workdir if workdir is not None \
            else os.getcwd()
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
        # Optional skills registry (cortex.skills), set by the
        # surface after construction; its catalog joins the tool
        # catalog injection when present.
        self.skills = None
        self._catalog_sent = False
        self.phase = "low-idle"

    def _event(self, kind: str, data: dict) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _set_phase(self, name: str) -> None:
        """Move the work phase and emit it as data. Only real
        transitions emit; a repeated phase is silent."""
        if name == self.phase or name not in PHASES:
            return
        self.phase = name
        self._event("phase", {"phase": name})

    def _ask_owner(self, prompt: str) -> bool:
        """Ask the owner through the injected asker, holding
        the phase at held-for-approval for the question's
        duration and returning to working when it resolves."""
        self._set_phase("held-for-approval")
        try:
            return self.ask(prompt).lower() == "y"
        finally:
            self._set_phase("working")

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

    def _refuse(self, name: str, primary: str,
                reason: str) -> None:
        """Conscience refusal (EMBER's deliberation gate):
        the action never runs, the owner sees the reason on
        the surface, the model is told why, and the refusal
        is journaled like every other decision."""
        self._event("conscience_refusal", {
            "name": name, "path": primary, "reason": reason,
        })
        self._event("tool_end", {
            "name": name, "path": primary, "ok": False,
            "detail": "refused by Lexis itself",
            "duration": 0.0,
        })
        self._turn_tools.append({
            "name": name, "ok": False, "path": primary,
            "detail": "refused by Lexis itself",
        })
        self.ledger.append_event(
            self.session_id, "conscience", reason)
        feedback = (f"[HASIL {name} {primary}: DITOLAK OLEH "
                    f"LEXIS SENDIRI: {reason}]")
        self.vault.add("user", feedback)
        self.ledger.append_message(
            self.session_id, "user", feedback)
        self.emit_line(
            f"  [SISTEM: Lexis menolak: {reason}]\n")

    def _do_write(self, path: str, content: str) -> str:
        """Execute one write marker through the warden and, in ASK
        modes, the owner. Returns 'written', or 'stopped' when the
        write was held, declined, or failed (the turn then ends,
        as the original ended it after a write decision)."""
        path = self._abs(path)
        refusal = conscience_mod.deliberate(
            "write_file", path, self.warden.mode, self.root,
            self.workdir)
        if refusal is not None:
            self._refuse("write_file", path, refusal)
            return "stopped"
        risk = self.forge.risk_of("write_file")
        decision = self.warden.decide(risk)
        try:
            self.emit_line(f"  [IZIN: Lexis ingin menulis file '{path}']")
            self._event("approval_needed", {
                "name": "write_file", "path": path, "content": content,
                "mode": self.warden.mode,
                "warn_once": decision == WARN,
            })
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
            elif decision in (ASK, WARN):
                prompt = (
                    "  Peringatan BLAZE (satu kali untuk kelas ini): "
                    "Izinkan dan jangan tanya lagi sesi ini? (y/n): "
                    if decision == WARN else "  Izinkan? (y/n): "
                )
                allowed = self._ask_owner(prompt)
                if allowed and decision == WARN:
                    self.warden.note_warned(risk)
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
            self._set_phase("working")
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

    def _ensure_catalog(self) -> None:
        """Teach the extended toolset once per session. The persona
        is never touched: the catalog rides as an engine system
        notice in the conversation itself, in the same register as
        the [HASIL ...] feedback the model already learns from.
        A resumed session that already carries it is left alone."""
        if self._catalog_sent:
            return
        self._catalog_sent = True
        for m in self.vault.messages():
            if CATALOG_MARK in (m.get("content") or ""):
                return
        text = CATALOG_TEXT
        if self.skills is not None:
            extra = self.skills.catalog_text()
            if extra:
                text = text + "\n" + extra
        self.vault.add("user", text)
        self.ledger.append_message(self.session_id, "user", text)

    def _abs(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(
            self.workdir, path
        )

    def _run_extended_tools(self, full, started, model_used,
                            prompt_tokens):
        """Execute at most one extended tool marker from a reply.

        Returns "tool_done" (feedback fed back, the completion
        loop continues), "tool_stopped" (the warden or the owner
        held it; the turn ends), or None (no extended marker).
        Write and exec risks pass the same approval path as file
        writes; read risks run directly, like file reads."""
        spec = None
        edit = forge_mod.find_edit_marker(full)
        if edit is not None:
            path, old, new = edit
            path = self._abs(path)
            spec = {
                "name": "edit_file", "risk": "write",
                "primary": path,
                "preview": f"{old}\n->\n{new}",
                "run": lambda: self.forge.call(
                    "edit_file", path=path, old=old, new=new),
                "ok_feedback": f"[HASIL EDIT FILE {path}]: "
                               "potongan berhasil diganti.",
                "detail": "passage replaced",
            }
        if spec is None:
            command = forge_mod.find_line_marker(full, "RUN")
            if command:
                spec = {
                    "name": "run_command", "risk": "exec",
                    "primary": command, "preview": command,
                    "stream_args": {"command": command,
                                    "cwd": self.workdir},
                    "run": lambda: self.forge.call(
                        "run_command", command=command,
                        cwd=self.workdir),
                    "ok_feedback": f"[HASIL PERINTAH `{command}`]:\n"
                                   "{result}",
                    "detail": "command",
                }
        if spec is None:
            target = forge_mod.find_bracket_marker(full, "RUN_TESTS")
            if target:
                path = self._abs(target)
                spec = {
                    "name": "run_tests", "risk": "exec",
                    "primary": path, "preview": f"tests in {path}",
                    "stream_args": {"path": path},
                    "run": lambda: self.forge.call(
                        "run_tests", path=path),
                    "ok_feedback": f"[HASIL TES di {path}]:\n"
                                   "{result}",
                    "detail": "tests",
                }
        if spec is None:
            query = forge_mod.find_line_marker(full, "SEARCH")
            if query:
                if "::" in query:
                    pattern, root = (p.strip() for p in
                                     query.split("::", 1))
                else:
                    pattern, root = query, "."
                root = self._abs(root)
                spec = {
                    "name": "search_text", "risk": "read",
                    "primary": pattern, "preview": pattern,
                    "run": lambda: self.forge.call(
                        "search_text", pattern=pattern, root=root),
                    "ok_feedback": f"[HASIL PENCARIAN '{pattern}' "
                                   f"di {root}]:\n{{result}}",
                    "detail": "search",
                }
        if spec is None:
            target = forge_mod.find_bracket_marker(full, "LIST_DIR")
            if target:
                path = self._abs(target)
                spec = {
                    "name": "list_dir", "risk": "read",
                    "primary": path, "preview": path,
                    "run": lambda: self.forge.call(
                        "list_dir", path=path),
                    "ok_feedback": f"[HASIL LIST {path}]:\n"
                                   "{result}",
                    "detail": "list",
                }
        if spec is None:
            url = forge_mod.find_bracket_marker(full, "FETCH")
            if url:
                spec = {
                    "name": "fetch_url", "risk": "read",
                    "primary": url, "preview": url,
                    "run": lambda: self.forge.call(
                        "fetch_url", url=url),
                    "ok_feedback": f"[HASIL AMBIL {url}]:\n"
                                   "{result}",
                    "detail": "fetch",
                }
        if spec is None:
            url = forge_mod.find_bracket_marker(full, "BROWSE")
            if url:
                spec = {
                    "name": "browse_page", "risk": "read",
                    "primary": url, "preview": url,
                    "run": lambda: self.forge.call(
                        "browse_page", url=url),
                    "ok_feedback": f"[HASIL BUKA {url}]:\n"
                                   "{result}",
                    "detail": "browse",
                }
        if spec is None:
            slug = forge_mod.find_bracket_marker(full, "USE_SKILL")
            if slug:
                return self._use_skill(
                    slug, started, model_used, prompt_tokens)
            return None

        name = spec["name"]
        primary = spec["primary"]
        refusal = conscience_mod.deliberate(
            name, primary, self.warden.mode, self.root,
            self.workdir)
        if refusal is not None:
            self._refuse(name, primary, refusal)
            self._finish("tool_done", started, model_used,
                         prompt_tokens, full)
            return "tool_done"
        if spec["risk"] in ("write", "exec"):
            self.emit_line(
                f"  [IZIN: Lexis ingin menjalankan {name} '{primary}']"
            )
            decision = self.warden.decide(spec["risk"])
            self._event("approval_needed", {
                "name": name, "path": primary,
                "content": spec["preview"],
                "mode": self.warden.mode,
                "warn_once": decision == WARN,
            })
            if decision == DENY:
                self._turn_tools.append({
                    "name": name, "ok": False, "path": primary,
                    "detail": "held by plan mode",
                })
                self.emit_line(
                    "  [SISTEM: Mode rencana aktif: tool ditahan.]\n"
                )
                return "tool_stopped"
            allowed = False
            if decision == ALLOW:
                allowed = True
            elif decision in (ASK, WARN):
                prompt = (
                    "  Peringatan BLAZE (satu kali untuk kelas ini): "
                    "Izinkan dan jangan tanya lagi sesi ini? (y/n): "
                    if decision == WARN else "  Izinkan? (y/n): "
                )
                allowed = self._ask_owner(prompt)
                if allowed and decision == WARN:
                    self.warden.note_warned(spec["risk"])
            if not allowed:
                self._turn_tools.append({
                    "name": name, "ok": False, "path": primary,
                    "detail": "not approved",
                })
                self.emit_line("  [SISTEM: Dibatalkan.]\n")
                return "tool_stopped"

        self._set_phase("working")
        self._event("tool_start", {"name": name, "path": primary})
        t0 = time.time()
        try:
            if spec.get("stream_args") is not None:
                # Live output (Master, 2026-11-11): command and
                # test lines reach the surface as they happen.
                result = self.forge.call_stream(
                    name,
                    lambda line: self._event(
                        "tool_output",
                        {"name": name, "text": line}),
                    **spec["stream_args"])
            else:
                result = spec["run"]()
        except Exception as e:
            self._event("tool_end", {
                "name": name, "path": primary, "ok": False,
                "detail": str(e), "duration": time.time() - t0,
            })
            self._turn_tools.append({
                "name": name, "ok": False, "path": primary,
                "detail": str(e),
            })
            feedback = f"[HASIL {name} {primary}: GAGAL: {e}]"
            self.vault.add("user", feedback)
            self.ledger.append_message(
                self.session_id, "user", feedback
            )
            self.emit_line(f"  [SISTEM ERROR: {e}]\n")
            self._finish("tool_done", started, model_used,
                         prompt_tokens, full)
            return "tool_done"
        detail = spec["detail"]
        if name in ("run_command", "run_tests"):
            detail = str(result).splitlines()[0] if result else ""
        self._event("tool_end", {
            "name": name, "path": primary, "ok": True,
            "detail": detail, "duration": time.time() - t0,
        })
        self._turn_tools.append({
            "name": name, "ok": True, "path": primary,
            "detail": detail,
        })
        feedback = spec["ok_feedback"].replace("{result}", str(result))
        self.vault.add("user", feedback)
        self.ledger.append_message(self.session_id, "user", feedback)
        self.emit_line(f"  [SISTEM: {name} selesai.]\n")
        self.ledger.append_event(
            self.session_id, "tool", f"{name} {primary}"
        )
        self._finish("tool_done", started, model_used,
                     prompt_tokens, full)
        return "tool_done"

    def _use_skill(self, slug, started, model_used, prompt_tokens):
        """Load one active skill's body into the conversation
        (progressive disclosure: the catalog carried only its
        name and description until now)."""
        body = self.skills.load_body(slug) if self.skills else None
        self._set_phase("working")
        self._event("tool_start", {"name": "use_skill", "path": slug})
        if body is None:
            self._event("tool_end", {
                "name": "use_skill", "path": slug, "ok": False,
                "detail": "skill not active", "duration": 0.0,
            })
            self._turn_tools.append({
                "name": "use_skill", "ok": False, "path": slug,
                "detail": "skill not active",
            })
            feedback = (f"[HASIL SKILL {slug}: GAGAL: skill tidak "
                        "aktif atau tidak dikenal]")
        else:
            self._event("tool_end", {
                "name": "use_skill", "path": slug, "ok": True,
                "detail": "body loaded", "duration": 0.0,
            })
            self._turn_tools.append({
                "name": "use_skill", "ok": True, "path": slug,
                "detail": "body loaded",
            })
            feedback = f"[ISI SKILL {slug}]:\n{body}"
            self.ledger.append_event(
                self.session_id, "tool", f"use_skill {slug}"
            )
        self.vault.add("user", feedback)
        self.ledger.append_message(self.session_id, "user", feedback)
        self._finish("tool_done", started, model_used,
                     prompt_tokens, "")
        return "tool_done"

    def evolve_skill(self, slug: str) -> dict:
        """Draft a new skill from this session's verified work
        (Step 3). The evidence gate runs first: without a judge
        'pass' in this session there is nothing to distill. The
        model writes the body; evolve.create_draft builds the
        frontmatter and puts the draft through the registry's
        scan, where it waits for the owner's approval."""
        from . import evolve as evolve_mod

        if self.skills is None:
            return {"ok": False,
                    "reason": "skill registry is not ready"}
        ok, evidence = evolve_mod.session_evidence(
            self.ledger, self.session_id)
        if not ok:
            return {
                "ok": False,
                "reason": "no verified success in this session "
                          "yet: finish a task that passes "
                          "verification first",
            }
        convo = [
            m for m in self.vault.messages()
            if m["role"] in ("user", "assistant")
        ][-16:]
        instruction = {
            "role": "user",
            "content": (
                "Distill the verified work above into a reusable "
                "skill for future sessions. Answer in exactly "
                "this shape: the first line is [SKILL_DESC: a "
                "one-line description of the general situation "
                "this skill applies to], then the skill body in "
                "Markdown with exactly these sections: "
                "'## When to use it', '## The rules', "
                "'## Worked example', '## How to check the "
                "result'. State the rules as project-wide "
                "conventions that hold anywhere in the project. "
                "Preserve concrete values verbatim inside the "
                "rules: names, tokens, markers, and exact "
                "commands appear literally, never generalized "
                "into placeholders like 'token X'. This "
                "session's folder, file names, and function are "
                "one worked example only: they belong in the "
                "example section, labelled as an example, and "
                "never limit the scope of the rules. Write only "
                "the description line and the body, no preamble."
            ),
        }
        api_key = bridge.current_key(self.root)
        model = self.compass.route("draft a skill")
        reply = ""
        try:
            for delta in bridge.stream_chat(
                    model, convo + [instruction], api_key):
                reply += delta
        except Exception as e:
            return {"ok": False,
                    "reason": f"drafting call failed: {e}"}
        description, body = evolve_mod.split_draft(
            judge_mod.visible_text(reply))
        if not body:
            return {"ok": False,
                    "reason": "the drafting reply was unusable"}
        return evolve_mod.create_draft(
            self.root, self.skills, self.ledger, self.session_id,
            slug, description, body, evidence)

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
        self._ensure_catalog()
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
            if outcome not in ("file_read", "write_done", "tool_done"):
                self._set_phase("dimming")
                return outcome
            actions += 1
            if actions >= 25:
                self._set_phase("dimming")
                # Safety valve: the original looped reads without a
                # cap; 25 consecutive tool actions in one turn is a
                # runaway, so the turn ends with what it has.
                return "done"

    def _turn_once(self, user_text: str) -> str:
        """One model call plus its marker handling. Returns 'done',
        'file_read', 'write_done', or 'cancelled'."""
        self._turn_tools = []
        started = time.time()
        self._set_phase("thinking")
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
                        self._set_phase("typing")
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
            read_path = self._abs(read_path)
            try:
                self._set_phase("working")
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

        tool_outcome = self._run_extended_tools(
            full, started, model_used, prompt_tokens
        )
        if tool_outcome == "tool_done":
            return "tool_done"
        # "tool_stopped" (held or declined) and None (no extended
        # marker) both end at the store below, like a finished turn.

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
