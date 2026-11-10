# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Vault: layered memory.

Fase 1: the live conversation lives in memory exactly like the original
main.py list. The config registry (every Markdown file in config/, with
its hash) is recorded in the ledger at startup: the whole config is
known and verifiable, but Fase 1 does not inject config content into
the conversation, because the original did not either. Layered
hot/warm/cold memory and episodic recall arrive in Fase 3 under the
anti-forgetting doctrine: nothing important lives only in RAM again.
"""

import hashlib
import os
import re

from . import persona_data

_DECISION = re.compile(
    r"\b(decid|agree|setuju|memutus|keputusan|pilih|chosen)", re.I
)
_PROMISE = re.compile(r"\b(will|promise|janji|akan)\b", re.I)
_PERSONAL = re.compile(
    r"^(my|i|aku|saya)\b|\b(prefer|name is|nama saya|suka|ingat|remember)\b",
    re.I,
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def extract_facts(text: str):
    """Deterministic fact extraction from one owner message.

    Returns up to 5 (kind, sentence) pairs where kind is 'decision',
    'promise', or 'fact'. Only clear owner statements qualify; chat
    that matches nothing yields nothing. This is the anti-forgetting
    net: statements are lifted into the cold tier before any context
    compaction can fold the raw message away."""
    found = []
    for raw in _SENTENCE.findall(text or ""):
        sentence = raw.strip()
        if len(sentence) < 12:
            continue
        if _DECISION.search(sentence):
            kind = "decision"
        elif _PROMISE.search(sentence) and _PERSONAL.search(sentence):
            kind = "promise"
        elif _PERSONAL.search(sentence):
            kind = "fact"
        else:
            continue
        found.append((kind, sentence))
        if len(found) >= 5:
            break
    return found


class Vault:
    def __init__(self) -> None:
        self._messages = []

    def bootstrap(self):
        """Build the exact opening messages of the original main.py:
        the system prompt plus its few-shot pair, byte-identical
        (persona_data is generated from main.py by AST extraction)."""
        msgs = [{"role": "system", "content": persona_data.SYSTEM_PROMPT}]
        for role, content in persona_data.FEWSHOT:
            msgs.append({"role": role, "content": content})
        self._messages = msgs
        return self.messages()

    def register_config(self, root: str, ledger) -> list:
        """Register every config/*.md in state.db (read-only import):
        hash registry plus the full text stored as a versioned
        document, so the whole configuration lives inside state.db
        and no edit is ever lost. The source files are never altered,
        and Fase 1/2 do not inject config content into conversations.
        Locked files (JAILBREAK.md) are stored exactly like the rest:
        read-only here as everywhere else."""
        registered = []
        cfg = os.path.join(root, "config")
        if os.path.isdir(cfg):
            for name in sorted(os.listdir(cfg)):
                if name.endswith(".md"):
                    with open(os.path.join(cfg, name), "rb") as f:
                        data = f.read()
                    digest = hashlib.sha256(data).hexdigest()
                    ledger.register_config_doc(name, digest, len(data))
                    ledger.store_document(
                        name, data.decode("utf-8", errors="replace"), digest
                    )
                    registered.append(name)
        return registered

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})

    def messages(self):
        return list(self._messages)

    def replace_all(self, messages) -> None:
        self._messages = [dict(m) for m in messages]

    # --- Fase 3: the three tiers -------------------------------------
    # Hot tier is the live conversation above. Warm tier is tagged
    # episodes (past sessions in the ledger). Cold tier is durable
    # facts in state.db, lifted out of conversations by extraction
    # and by compaction, and never held only in RAM again.

    def remember(self, ledger, session_id: int, kind: str, text: str,
                 tags: str = "") -> bool:
        return ledger.add_fact(session_id, kind, text, tags)

    def learn_from(self, ledger, session_id: int, text: str) -> int:
        """Extract and store the durable statements in one message.
        Returns how many new facts were written."""
        stored = 0
        for kind, sentence in extract_facts(text):
            if self.remember(ledger, session_id, kind, sentence):
                stored += 1
        return stored

    def recall(self, ledger, query=None, kind=None, limit=20):
        """Cold-tier recall: newest durable facts first, optionally
        filtered by keyword or kind."""
        return ledger.facts(kind=kind, query=query, limit=limit)

    def episodes(self, ledger, limit=20):
        """Warm tier: past sessions as tagged episodes."""
        return ledger.sessions(limit=limit)

    def tag_episode(self, ledger, session_id: int, tag: str) -> None:
        ledger.tag_session(session_id, tag)
