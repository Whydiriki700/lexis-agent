# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Ledger: durable sessions, step journal, and telemetry in state.db.

One SQLite database holds sessions and their messages (so a session can
be resumed whole), an event journal (turns, tool calls, model changes),
and the config document registry. Secrets are never written here.
"""

import os
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS documents (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    content TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    PRIMARY KEY (name, version)
);
"""


class Ledger:
    def __init__(self, db_path: str) -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db_path = db_path
        # The Visor runs the agent loop on a worker thread while the
        # plain CLI is single-threaded. SQLite objects are thread-bound,
        # so each thread gets its own connection to the same file
        # (WAL mode keeps them consistent); writes are lock-guarded.
        self._lock = threading.Lock()
        self._local = threading.local()
        self._all_conns = []
        _ = self._conn  # create this thread's connection + schema

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(_SCHEMA)
        conn.commit()
        self._all_conns.append(conn)
        return conn

    @property
    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def start_session(self, model: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, model) VALUES (?, ?)",
            (_now(), model),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def append_message(self, session_id: int, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session_id, role, content, _now()),
            )
            self._conn.commit()

    def append_event(self, session_id: int, kind: str, detail: str) -> None:
        with self._lock:
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

    def store_document(self, name: str, content: str, sha256: str) -> int:
        """Store a Markdown document's full text as a new version.
        Identical content (same hash) does not create a new version;
        earlier versions are never overwritten, so an edit history
        survives (anti-forgetting doctrine). Returns the version."""
        data = content.encode("utf-8")
        row = self._conn.execute(
            "SELECT version, sha256 FROM documents WHERE name = ? "
            "ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row and row[1] == sha256:
            return int(row[0])
        version = int(row[0]) + 1 if row else 1
        self._conn.execute(
            "INSERT INTO documents (name, version, sha256, size, content, "
            "stored_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, version, sha256, len(data), content, _now()),
        )
        self._conn.commit()
        return version

    def latest_document(self, name: str):
        row = self._conn.execute(
            "SELECT version, sha256, content FROM documents WHERE name = ? "
            "ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return {"version": row[0], "sha256": row[1], "content": row[2]}

    def document_names(self):
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT name FROM documents ORDER BY name"
            ).fetchall()
        ]

    def session_count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        )

    def close(self) -> None:
        for conn in self._all_conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._all_conns = []
