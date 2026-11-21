# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Forge: the schema tool registry and executor.

Every tool has a JSON schema, a risk class, and a handler. Fase 1 ships
the two original tools (read file, write file). The original text-marker
protocol ([READ_FILE: ...] / [WRITE_FILE: ...] [/WRITE_FILE]) is parsed
here and translated into registry calls, so model behavior stays
identical while the execution path is structured.

The full toolset (Master's build order, 2026-11-10 22.55) joins the
same registry under the same warden gate: edit_file, search_text,
list_dir, run_command (Lexis's own terminal), run_tests, fetch_url,
and browse_page. The model learns these from an engine-injected
catalog (see pulse), never from the persona.
"""

import html as html_mod
import os
import re
import subprocess
import sys

READ_MARKER = "[READ_FILE:"
WRITE_MARKER = "[WRITE_FILE:"
WRITE_END = "[/WRITE_FILE]"
EDIT_MARKER = "[EDIT_FILE:"
EDIT_WITH = "[WITH]"
EDIT_END = "[/EDIT_FILE]"

TOOL_ORDER = (
    "read_file", "write_file", "edit_file", "search_text",
    "list_dir", "run_command", "run_tests", "fetch_url",
    "browse_page",
)

TOOL_SCHEMAS = {
    "read_file": {
        "name": "read_file",
        "description": "Read a UTF-8 text file and return its content.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "risk": "read",
    },
    "write_file": {
        "name": "write_file",
        "description": "Write UTF-8 text content to a file, creating folders.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        "risk": "write",
    },
    "edit_file": {
        "name": "edit_file",
        "description": "Replace one exact passage in a file. The old "
                       "text must occur exactly once.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
        "risk": "write",
    },
    "search_text": {
        "name": "search_text",
        "description": "Search text files under a folder for a string.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "root": {"type": "string"},
            },
            "required": ["pattern", "root"],
        },
        "risk": "read",
    },
    "list_dir": {
        "name": "list_dir",
        "description": "List a folder's entries.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "risk": "read",
    },
    "run_command": {
        "name": "run_command",
        "description": "Run a terminal command in the profile home "
                       "with a 60 second limit; returns its exit code "
                       "and output.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        "risk": "exec",
    },
    "run_tests": {
        "name": "run_tests",
        "description": "Run the test suite in a folder (unittest "
                       "discovery, or pytest when available).",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "risk": "exec",
    },
    "fetch_url": {
        "name": "fetch_url",
        "description": "Fetch a web page and return its text.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "risk": "read",
    },
    "browse_page": {
        "name": "browse_page",
        "description": "Open a web page as text plus its numbered "
                       "outbound links, to follow next.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "risk": "read",
    },
}


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> str:
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _edit_file(path: str, old: str, new: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    count = content.count(old)
    if count == 0:
        raise ValueError("old text not found in file")
    if count > 1:
        raise ValueError(
            f"old text occurs {count} times; it must be unique"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.replace(old, new, 1))
    return path


_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".svn"}
_TEXT_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log",
    ".yaml", ".yml", ".toml", ".ini", ".html", ".css", ".xml",
    ".sh", ".bat", ".ps1", ".java", ".c", ".h", ".cpp", ".go",
    ".rs", ".rb", ".php", ".sql",
}


def _search_text(pattern: str, root: str) -> str:
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() not in _TEXT_EXTS:
                continue
            full = os.path.join(dirpath, name)
            try:
                with open(full, "r", encoding="utf-8",
                          errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if pattern in line:
                            hits.append(
                                f"{full}:{i}: {line.strip()[:160]}"
                            )
                            if len(hits) >= 100:
                                return "\n".join(hits) + \
                                    "\n[100 hasil pertama]"
            except OSError:
                continue
    return "\n".join(hits) if hits else "(tidak ada hasil)"


def _list_dir(path: str) -> str:
    entries = sorted(os.listdir(path))
    lines = []
    for name in entries[:200]:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            lines.append(name + "/")
        else:
            lines.append(f"{name} ({os.path.getsize(full)} B)")
    if len(entries) > 200:
        lines.append(f"[{len(entries) - 200} entri lain tidak ditampilkan]")
    return "\n".join(lines) if lines else "(folder kosong)"


_ENV_DROP = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD")


def _scrubbed_env() -> dict:
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if any(part in upper for part in _ENV_DROP):
            del env[key]
    return env


def _run(command: str, cwd: str, timeout: int, cap: int) -> str:
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, timeout=timeout,
            capture_output=True, text=True, errors="replace",
            env=_scrubbed_env(),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        return f"exit=timeout\n[Perintah melewati batas {timeout} detik.]"
    if len(out) > cap:
        out = out[:cap] + f"\n[Output dipotong di {cap} karakter.]"
    return f"exit={code}\n{out}"


def _run_stream(command: str, cwd: str, timeout: int, cap: int,
                emit) -> str:
    """_run with live output: every line is handed to emit()
    the moment the process prints it, so the surface shows
    the work as it happens instead of only at the end
    (Master, 2026-11-11: live coding must be fully live).
    The deadline is checked between lines; a process that
    prints nothing can still overrun until its first line
    or its exit. The returned string matches _run exactly."""
    import time as _time

    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
            env=_scrubbed_env(),
        )
    except Exception as e:
        return f"exit=error\n{e}"
    parts = []
    size = 0
    deadline = _time.time() + timeout
    timed_out = False
    try:
        for line in proc.stdout:
            parts.append(line)
            size += len(line)
            emit(line.rstrip("\r\n"))
            if _time.time() > deadline:
                timed_out = True
                proc.kill()
                break
    finally:
        proc.wait()
    out = "".join(parts)
    code = proc.returncode
    if timed_out:
        return f"exit=timeout\n[Perintah melewati batas {timeout} detik.]"
    if len(out) > cap:
        out = out[:cap] + f"\n[Output dipotong di {cap} karakter.]"
    return f"exit={code}\n{out}"


def _run_command(command: str, cwd: str) -> str:
    return _run(command, cwd, timeout=60, cap=8000)


def _run_tests(path: str) -> str:
    try:
        import pytest  # noqa: F401
        cmd = (f'"{sys.executable}" -m pytest -q "{path}"')
    except ImportError:
        cmd = (f'"{sys.executable}" -m unittest discover '
               f'-s "{path}" -t "{path}"')
    return _run(cmd, path, timeout=300, cap=6000)


def _fetch_raw(url: str) -> str:
    import requests

    resp = requests.get(
        url, timeout=20,
        headers={"User-Agent": "Lexis/0.1 (text browser)"},
    )
    resp.raise_for_status()
    return resp.text


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(
    r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I
)


def _html_to_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw)
    text = _ANY_TAG.sub(" ", text)
    text = html_mod.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _fetch_url(url: str) -> str:
    raw = _fetch_raw(url)
    text = _html_to_text(raw) if "<" in raw[:2000] else raw
    if len(text) > 12000:
        text = text[:12000] + "\n[Isi dipotong di 12000 karakter.]"
    return text


def _browse_page(url: str) -> str:
    from urllib.parse import urljoin

    raw = _fetch_raw(url)
    text = _html_to_text(raw) if "<" in raw[:2000] else raw
    if len(text) > 8000:
        text = text[:8000] + "\n[Isi dipotong di 8000 karakter.]"
    links = []
    seen = set()
    for href, label in _LINK_RE.findall(raw):
        absolute = urljoin(url, href)
        if absolute in seen or absolute.startswith(
            ("javascript:", "mailto:", "#")
        ):
            continue
        seen.add(absolute)
        label = _ANY_TAG.sub("", label).strip()[:60] or absolute
        links.append(f"[{len(links) + 1}] {label} -> {absolute}")
        if len(links) >= 40:
            break
    if links:
        text += "\n\nTAUTAN:\n" + "\n".join(links)
    return text


_HANDLERS = {
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "search_text": _search_text,
    "list_dir": _list_dir,
    "run_command": _run_command,
    "run_tests": _run_tests,
    "fetch_url": _fetch_url,
    "browse_page": _browse_page,
}


class Forge:
    def schemas(self):
        return [TOOL_SCHEMAS[name] for name in TOOL_ORDER]

    def risk_of(self, name: str) -> str:
        return TOOL_SCHEMAS[name]["risk"]

    def call(self, name: str, **kwargs):
        return _HANDLERS[name](**kwargs)

    def call_stream(self, name: str, emit, **kwargs):
        """Run an exec tool with its output streamed line by
        line to emit(). Only run_command and run_tests have
        output worth watching; anything else is a plain call."""
        if name == "run_command":
            return _run_stream(
                kwargs["command"], kwargs.get("cwd") or
                os.getcwd(), timeout=60, cap=8000, emit=emit)
        if name == "run_tests":
            path = kwargs["path"]
            try:
                import pytest  # noqa: F401
                cmd = f'"{sys.executable}" -m pytest -q "{path}"'
            except ImportError:
                cmd = (f'"{sys.executable}" -m unittest discover '
                       f'-s "{path}" -t "{path}"')
            return _run_stream(cmd, path, timeout=300, cap=6000,
                               emit=emit)
        return self.call(name, **kwargs)


def _angle_arg(text: str, tag: str):
    """The argument of an angle-bracket <TAG: argument> marker,
    or None. Models sometimes XML-ify the protocol (Master's
    session, 2026-11-11: a <LIST_DIR: workspace> attempt);
    the dialect is understood as a fallback, never required,
    and the square form always wins when both appear."""
    marker = f"<{tag}:"
    if marker in text and ">" in text:
        start = text.find(marker) + len(marker)
        end = text.find(">", start)
        return text[start:end].strip()
    return None


def find_read_marker(text: str):
    """Return the path from a [READ_FILE: path] marker, or None.
    Mirrors the original main.py parsing exactly."""
    if READ_MARKER in text and "]" in text:
        start = text.find(READ_MARKER) + len(READ_MARKER)
        end = text.find("]", start)
        return text[start:end].strip()
    return _angle_arg(text, "READ_FILE")


def find_write_marker(text: str):
    """Return (path, content) from a [WRITE_FILE: path] ... [/WRITE_FILE]
    marker, or None. Mirrors the original main.py parsing exactly.
    The angle dialect (<WRITE_FILE: path> ... </WRITE_FILE>) is
    accepted wherever it appears first."""
    sq = text.find(WRITE_MARKER) if WRITE_END in text else -1
    ag = text.find("<WRITE_FILE:") if "</WRITE_FILE>" in text else -1
    if sq == -1 and ag == -1:
        return None
    if ag != -1 and (sq == -1 or ag < sq):
        start = ag + len("<WRITE_FILE:")
        end = text.find(">", start)
        if end == -1:
            return None
        filename = text[start:end].strip()
        content_end = text.find("</WRITE_FILE>", end)
        if content_end == -1:
            return None
        return filename, text[end + 1:content_end].strip()
    start = text.find(WRITE_MARKER) + len(WRITE_MARKER)
    end = text.find("]", start)
    filename = text[start:end].strip()
    content_start = text.find("]", start) + 1
    content_end = text.find(WRITE_END)
    content = text[content_start:content_end].strip()
    return filename, content


def find_write_markers(text: str):
    """All complete (path, content) write markers in a reply, in
    order, each parsed exactly like find_write_marker. The
    original executed the first marker only; a reply that itself
    carries a whole multi-file plan is executed as a unit by the
    completion loop (see pulse.Pulse.handle_turn)."""
    out = []
    rest = text
    while True:
        one = find_write_marker(rest)
        if one is None:
            return out
        out.append(one)
        ends = [rest.find(WRITE_END), rest.find("</WRITE_FILE>")]
        ends = [e for e in ends if e != -1]
        if not ends:
            return out
        end = min(ends)
        token = (WRITE_END if rest.startswith(WRITE_END, end)
                 else "</WRITE_FILE>")
        rest = rest[end + len(token):]


def find_edit_marker(text: str):
    """Return (path, old, new) from an [EDIT_FILE: path] block:
    the old passage, the [WITH] separator, the new passage, and
    [/EDIT_FILE]. Mirrors the write marker's parsing style."""
    if EDIT_MARKER in text and EDIT_WITH in text and EDIT_END in text:
        start = text.find(EDIT_MARKER) + len(EDIT_MARKER)
        end = text.find("]", start)
        filename = text[start:end].strip()
        with_at = text.find(EDIT_WITH, end)
        end_at = text.find(EDIT_END, with_at)
        if with_at == -1 or end_at == -1:
            return None
        old = text[end + 1:with_at].strip()
        new = text[with_at + len(EDIT_WITH):end_at].strip()
        return filename, old, new
    if EDIT_MARKER not in text:
        # Angle dialect: <EDIT_FILE: path> old <WITH> new
        # </EDIT_FILE> (the [WITH] separator is accepted too).
        a_marker, a_end = "<EDIT_FILE:", "</EDIT_FILE>"
        if a_marker in text and a_end in text:
            start = text.find(a_marker) + len(a_marker)
            end = text.find(">", start)
            if end == -1:
                return None
            filename = text[start:end].strip()
            with_at, with_len = -1, 0
            for w in ("<WITH>", EDIT_WITH):
                at = text.find(w, end)
                if at != -1 and (with_at == -1 or at < with_at):
                    with_at, with_len = at, len(w)
            end_at = text.find(a_end, end)
            if with_at == -1 or end_at == -1 or with_at > end_at:
                return None
            old = text[end + 1:with_at].strip()
            new = text[with_at + with_len:end_at].strip()
            return filename, old, new
    return None


def find_bracket_marker(text: str, tag: str):
    """Return the argument of a single [TAG: argument] marker
    (read-style, argument ends at the first ]), or None."""
    marker = f"[{tag}:"
    if marker in text and "]" in text:
        start = text.find(marker) + len(marker)
        end = text.find("]", start)
        return text[start:end].strip()
    return _angle_arg(text, tag)


def find_line_marker(text: str, tag: str):
    """Return the argument of a [TAG: argument] marker that runs
    to the end of its line. Commands and search patterns may
    contain ] characters, so they do not close at a bracket."""
    marker = f"[{tag}:"
    if marker in text:
        start = text.find(marker) + len(marker)
        end = text.find("\n", start)
        line = text[start:] if end == -1 else text[start:end]
        line = line.strip()
        if line.endswith("]"):
            line = line[:-1].strip()
        return line
    marker = f"<{tag}:"
    if marker in text:
        start = text.find(marker) + len(marker)
        end = text.find("\n", start)
        line = text[start:] if end == -1 else text[start:end]
        line = line.strip()
        if line.endswith(">"):
            line = line[:-1].strip()
        return line
    return None
