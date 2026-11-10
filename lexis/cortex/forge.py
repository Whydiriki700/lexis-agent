# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Forge: the schema tool registry and executor.

Every tool has a JSON schema, a risk class, and a handler. Fase 1 ships
the two original tools (read file, write file). The original text-marker
protocol ([READ_FILE: ...] / [WRITE_FILE: ...] [/WRITE_FILE]) is parsed
here and translated into registry calls, so model behavior stays
identical while the execution path is structured. Lexis's own terminal
joins this registry in a later phase under the same warden gate.
"""

import os

READ_MARKER = "[READ_FILE:"
WRITE_MARKER = "[WRITE_FILE:"
WRITE_END = "[/WRITE_FILE]"

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


_HANDLERS = {"read_file": _read_file, "write_file": _write_file}


class Forge:
    def schemas(self):
        return [TOOL_SCHEMAS[name] for name in ("read_file", "write_file")]

    def risk_of(self, name: str) -> str:
        return TOOL_SCHEMAS[name]["risk"]

    def call(self, name: str, **kwargs):
        return _HANDLERS[name](**kwargs)


def find_read_marker(text: str):
    """Return the path from a [READ_FILE: path] marker, or None.
    Mirrors the original main.py parsing exactly."""
    if READ_MARKER in text and "]" in text:
        start = text.find(READ_MARKER) + len(READ_MARKER)
        end = text.find("]", start)
        return text[start:end].strip()
    return None


def find_write_marker(text: str):
    """Return (path, content) from a [WRITE_FILE: path] ... [/WRITE_FILE]
    marker, or None. Mirrors the original main.py parsing exactly."""
    if WRITE_MARKER in text and WRITE_END in text:
        start = text.find(WRITE_MARKER) + len(WRITE_MARKER)
        end = text.find("]", start)
        filename = text[start:end].strip()
        content_start = text.find("]", start) + 1
        content_end = text.find(WRITE_END)
        content = text[content_start:content_end].strip()
        return filename, content
    return None
