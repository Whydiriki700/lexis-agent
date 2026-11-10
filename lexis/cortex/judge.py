# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Judge: the verifier.

A completion claim stands only when signals outside the model's own
words agree: a written file must exist on disk with the bytes that
were promised, Python must parse with the interpreter's own parser,
JSON must parse, and the reply itself must be non-empty and free of
leaked tool protocol. Verdicts are pass, warn, or fail, always with
reasons in user language.
"""

import json
import os
import re

_READ_MARK = re.compile(r"\[READ_FILE:[^\]]*\]")


def visible_text(reply: str) -> str:
    """What the user actually sees of a reply: the read markers
    removed, everything from a write marker onward cut (the write
    card and the approval screen carry that content instead). The
    judge checks this text, never the raw protocol stream."""
    t = _READ_MARK.sub("", reply or "")
    idx = t.find("[WRITE_FILE:")
    if idx >= 0:
        t = t[:idx]
    return t


class Verdict:
    def __init__(self, status: str, reasons) -> None:
        self.status = status  # 'pass' | 'warn' | 'fail'
        self.reasons = list(reasons)

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def __repr__(self) -> str:
        return f"Verdict({self.status!r}, {self.reasons!r})"


def check_written_file(root: str, path: str, content: str):
    """External-signal checks for one written file. Returns a list of
    (ok, reason) pairs; an empty list means nothing checkable."""
    checks = []
    full = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(full):
        checks.append((False, f"The file {path} is not on disk."))
        return checks
    with open(full, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    # Newline style is not a content difference: a file that came
    # back with CRLF endings still holds what was written.
    if text.replace("\r\n", "\n") != content.replace("\r\n", "\n"):
        checks.append((False, f"The file {path} differs from what was written."))
    else:
        checks.append((True, f"The file {path} is on disk as written."))
    if path.endswith(".py"):
        try:
            compile(text, path, "exec")
            checks.append((True, "The Python code parses cleanly."))
        except SyntaxError as e:
            checks.append((False, f"The Python code does not parse: {e.msg}."))
    if path.endswith(".json"):
        try:
            json.loads(text)
            checks.append((True, "The JSON parses cleanly."))
        except ValueError:
            checks.append((False, "The JSON does not parse."))
    return checks


def verify_turn(reply: str, tools, root: str) -> Verdict:
    """Judge one finished turn. tools is a list of dicts with keys
    name, ok, and (for writes) path and content."""
    reasons = []
    status = "pass"

    def fail(reason):
        nonlocal status
        status = "fail"
        reasons.append(reason)

    def warn(reason):
        nonlocal status
        if status == "pass":
            status = "warn"
        reasons.append(reason)

    visible = visible_text(reply)
    worked = any(t.get("ok") for t in tools or [])
    if not visible.strip() and not worked:
        fail("The reply came back empty.")
    if ("[WRITE_FILE" in visible or "[READ_FILE" in visible
            or "[/WRITE_FILE]" in visible):
        fail("Tool protocol leaked into the visible reply.")
    for t in tools or []:
        if not t.get("ok", True):
            warn(f"A step did not complete: {t.get('name', 'tool')} "
                 f"({t.get('detail', 'no detail')}).")
        elif t.get("name") == "write_file" and t.get("path") is not None:
            for ok, reason in check_written_file(
                root, t["path"], t.get("content", "")
            ):
                if ok:
                    reasons.append(reason)
                else:
                    fail(reason)
    if status == "pass" and not reasons:
        reasons.append("All checks passed.")
    return Verdict(status, reasons)
