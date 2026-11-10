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
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_tags (
    session_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (session_id, tag)
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

    # --- Fase 3: cold-tier facts, episode tags, cost telemetry ---

    def add_fact(self, session_id: int, kind: str, text: str,
                 tags: str = "") -> bool:
        """Store one durable fact (cold tier). Identical text is stored
        once: memory must not fill with copies of the same fact.
        Returns True when a new fact was written."""
        row = self._conn.execute(
            "SELECT id FROM facts WHERE text = ?", (text,)
        ).fetchone()
        if row is not None:
            return False
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (session_id, kind, text, tags, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, kind, text, tags, _now()),
            )
            self._conn.commit()
        return True

    def facts(self, session_id=None, kind=None, query=None, limit=200):
        sql = "SELECT id, session_id, kind, text, tags, ts FROM facts"
        clauses, params = [], []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if query:
            clauses.append("text LIKE ?")
            params.append(f"%{query}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [
            {"id": r[0], "session_id": r[1], "kind": r[2], "text": r[3],
             "tags": r[4], "ts": r[5]}
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def fact_count(self, session_id=None, kind=None) -> int:
        sql = "SELECT COUNT(*) FROM facts"
        clauses, params = [], []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(self._conn.execute(sql, params).fetchone()[0])

    def tag_session(self, session_id: int, tag: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO session_tags (session_id, tag) "
                "VALUES (?, ?)",
                (session_id, tag),
            )
            self._conn.commit()

    def session_tags(self, session_id: int):
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT tag FROM session_tags WHERE session_id = ? "
                "ORDER BY tag",
                (session_id,),
            ).fetchall()
        ]

    def sessions(self, limit=20):
        rows = self._conn.execute(
            "SELECT id, started_at, model FROM sessions ORDER BY id DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "started_at": r[1], "model": r[2],
             "tags": self.session_tags(r[0])}
            for r in rows
        ]

    def record_cost(self, session_id: int, model: str, seconds: float,
                    prompt_tokens: int, reply_tokens: int,
                    outcome: str) -> None:
        """One finished task's cost record (telemetry for compass).
        Token counts are estimates (4 chars per token) and are stored
        labelled as such in the detail payload."""
        import json

        detail = json.dumps({
            "model": model, "seconds": round(seconds, 3),
            "prompt_tokens_est": int(prompt_tokens),
            "reply_tokens_est": int(reply_tokens),
            "outcome": outcome,
        })
        self.append_event(session_id, "cost", detail)

    def cost_rows(self):
        import json

        rows = []
        for (detail,) in self._conn.execute(
            "SELECT detail FROM events WHERE kind = 'cost' ORDER BY id"
        ).fetchall():
            try:
                rows.append(json.loads(detail))
            except ValueError:
                continue
        return rows

    def events(self, session_id: int, kind=None, limit: int = 200):
        """Event details for one session, oldest first, optionally
        filtered by kind. The judge's per-turn verdicts live here
        (kind 'judge'), which is what the evolve evidence gate
        reads."""
        if kind is None:
            cur = self._conn.execute(
                "SELECT detail FROM events WHERE session_id = ? "
                "ORDER BY id LIMIT ?",
                (session_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT detail FROM events WHERE session_id = ? "
                "AND kind = ? ORDER BY id LIMIT ?",
                (session_id, kind, limit),
            )
        return [row[0] for row in cur.fetchall()]

    def close(self) -> None:
        for conn in self._all_conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._all_conns = []
