# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Ledger: durable sessions, step journal, and telemetry in state.db.

One SQLite database holds sessions and their messages (so a session can
be resumed whole), an event journal (turns, tool calls, model changes),
and the config document registry. Secrets are never written here.
"""

import os
import sqlite3
from datetime import datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_docs (
    name TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    registered_at TEXT NOT NULL
);
"""


class Ledger:
    def __init__(self, db_path: str) -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def start_session(self, model: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, model) VALUES (?, ?)",
            (_now(), model),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def append_message(self, session_id: int, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )
        self._conn.commit()

    def append_event(self, session_id: int, kind: str, detail: str) -> None:
        self._conn.execute(
            "INSERT INTO events (session_id, kind, detail, ts) VALUES (?, ?, ?, ?)",
            (session_id, kind, detail, _now()),
        )
        self._conn.commit()

    def load_messages(self, session_id: int):
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def last_session_id(self):
        row = self._conn.execute("SELECT MAX(id) FROM sessions").fetchone()
        return row[0] if row and row[0] is not None else None

    def register_config_doc(self, name: str, sha256: str, size: int) -> None:
        self._conn.execute(
            "INSERT INTO config_docs (name, sha256, size, registered_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
            "sha256 = excluded.sha256, size = excluded.size, "
            "registered_at = excluded.registered_at",
            (name, sha256, size, _now()),
        )
        self._conn.commit()

    def config_docs(self):
        return self._conn.execute(
            "SELECT name, sha256, size FROM config_docs ORDER BY name"
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
