"""Dropped-file attachments (Master, 2026-11-10).

Dropping a file onto the terminal pastes its path into the
composer. This module turns such paths into real attachments:

* detection is stat-only and instant, so the interface never
  waits on it (Master's responsiveness rule);
* a text file's content joins the turn, capped, with an honest
  truncation note when it does not fit;
* an image is attached as a reference only: the current model
  line is text-only and this module never pretends otherwise;
* a sensitive file (.env, keys, credentials) is attached as a
  reference only, with a warning: its content never rides to a
  provider just because it was dropped;
* any other binary is a reference the model can still open with
  its file tools.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_LINES = 500
MAX_CHARS = 24000

_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".csv", ".tsv", ".log", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".html", ".htm", ".css", ".xml", ".sql",
    ".sh", ".bat", ".cmd", ".ps1", ".java", ".c", ".h", ".cpp",
    ".go", ".rs", ".rb", ".php",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials"}
_SENSITIVE_PARTS = ("secret", "credential", "private")
_SENSITIVE_EXTS = {".key", ".pem", ".p12", ".pfx", ".kdbx"}

_QUOTED = re.compile(r'"([^"\n]+)"|\'([^\'\n]+)\'')


def _is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    if name in _SENSITIVE_NAMES or name.startswith(".env"):
        return True
    if path.suffix.lower() in _SENSITIVE_EXTS:
        return True
    return any(part in name for part in _SENSITIVE_PARTS)


def _looks_text(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXTS:
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _as_file(candidate: str) -> Path | None:
    candidate = candidate.strip().strip(",;:)")
    if not candidate or len(candidate) < 3:
        return None
    try:
        path = Path(candidate).expanduser()
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def find_dropped_paths(text: str) -> list[Path]:
    """Existing files named in `text`, in order, de-duplicated.

    Quoted spans are tried first. Unquoted text is then scanned
    with longest-join reconstruction: a dropped path containing
    spaces arrives unquoted from most terminals, so consecutive
    words are joined and the LONGEST join that is a real file
    wins. That matters on real machines: with a profile folder
    like "Riki Wahyudi", the first word alone can itself be an
    existing file, and attaching that stranger instead of the
    dropped file is the failure this reconstruction prevents
    (found by System Creation's verification, 2026-11-10).
    A candidate only counts when it resolves to a real file on
    disk, so ordinary prose is never mistaken for an attachment.
    """
    found: list[Path] = []
    seen: set[str] = set()

    def consider(candidate: str) -> Path | None:
        path = _as_file(candidate)
        if path is None:
            return None
        key = str(path.resolve()).lower()
        if key in seen:
            return path
        seen.add(key)
        found.append(path)
        return path

    for match in _QUOTED.finditer(text):
        consider(match.group(1) or match.group(2))
    tokens = text.split()
    i = 0
    while i < len(tokens):
        hit_end = None
        for j in range(min(len(tokens), i + 8), i, -1):
            if _as_file(" ".join(tokens[i:j])) is not None:
                hit_end = j
                break
        if hit_end is None:
            i += 1
        else:
            consider(" ".join(tokens[i:hit_end]))
            i = hit_end
    return found


class Attachment:
    """One dropped file, classified and (for text) loaded."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.size = path.stat().st_size
        self.lines: int | None = None
        self.lines_exact = True
        self.truncated = False
        self._body: str | None = None
        if _is_sensitive(path):
            self.kind = "sensitive"
        elif path.suffix.lower() in _IMAGE_EXTS:
            self.kind = "image"
        elif _looks_text(path):
            self.kind = "text"
            self._load()
        else:
            self.kind = "binary"

    def _load(self) -> None:
        # Everything here is budget-bounded: a huge file must
        # never stall the interface or flood the context. Even
        # the line count stops at a scan budget and then reports
        # itself as a floor ("N+ lines"), never a fake total.
        with open(self.path, "rb") as fh:
            raw = fh.read(MAX_CHARS * 2)
        text = raw.decode("utf-8", errors="replace")
        budget = 8 * 1024 * 1024
        counted = 0
        scanned = 0
        exact = True
        with open(self.path, "rb") as fh:
            while scanned < budget:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                scanned += len(chunk)
                counted += chunk.count(b"\n")
            if scanned < self.size:
                exact = False
        if exact and text and not text.endswith("\n"):
            counted += 1
        self.lines = counted
        self.lines_exact = exact
        lines = text.splitlines()
        body = "\n".join(lines[:MAX_LINES])[:MAX_CHARS]
        self.truncated = (
            not exact or counted > MAX_LINES or len(text) > MAX_CHARS
        )
        self._body = body

    # -- presentation -------------------------------------------------

    def _size_text(self) -> str:
        if self.size >= 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        if self.size >= 1024:
            return f"{self.size / 1024:.1f} KB"
        return f"{self.size} B"

    def card_text(self) -> str:
        """The one-line card shown in the chat for this file."""
        base = f"📎 {self.name} · {self._size_text()}"
        if self.kind == "text":
            base += f" · {self.lines}{'' if self.lines_exact else '+'} lines"
            if self.truncated:
                base += f" · first {MAX_LINES} lines attached"
        elif self.kind == "image":
            base += " · image, reference only (text-only model)"
        elif self.kind == "sensitive":
            base += " · ⚠ sensitive: content withheld"
        else:
            base += " · binary, reference only"
        return base

    def model_block(self) -> str:
        """What the model receives for this attachment."""
        head = f"[Attached file: {self.name} · {self.path}]"
        if self.kind == "text":
            note = ""
            if self.truncated:
                total = (
                    f"{self.lines} lines total"
                    if self.lines_exact
                    else f"at least {self.lines} lines"
                )
                note = (
                    f"\n[Truncated: showing the first {MAX_LINES} "
                    f"lines / {MAX_CHARS} characters of {total}.]"
                )
            return f"{head}\n{self._body}{note}"
        if self.kind == "image":
            return (
                f"{head}\n[Image file attached as a reference. The "
                "current model is text-only and cannot view image "
                "content; the file can be handled as a path.]"
            )
        if self.kind == "sensitive":
            return (
                f"{head}\n[Sensitive file: its content was NOT "
                "attached. The owner dropped it as a reference "
                "only; never ask for its secrets to be pasted.]"
            )
        return (
            f"{head}\n[Binary file attached as a reference; its "
            "content was not inlined. Use file tools if needed.]"
        )


def scan(text: str) -> list[Attachment]:
    """All attachments for a composer message (may be empty)."""
    return [Attachment(p) for p in find_dropped_paths(text)]


def enrich(text: str, attachments: list[Attachment]) -> str:
    """The message as the model receives it: owner's words first,
    then each attachment block, clearly delimited."""
    if not attachments:
        return text
    blocks = "\n\n".join(a.model_block() for a in attachments)
    return f"{text}\n\n{blocks}"


def describe_paths(text: str) -> list[Attachment]:
    """Detection only (stat + classification), for callers that
    show the cards before the turn starts."""
    return scan(text)
