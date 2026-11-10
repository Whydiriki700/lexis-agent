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

from . import persona_data


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
