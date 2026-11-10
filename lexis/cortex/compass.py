# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Compass: model catalog, routing, and fallback for Lexis.

The catalog is the original main.py catalog, unchanged. The default
model was changed by Master's decision (2026-11-10) to
deepseek-v4.1-flash-1017-fast: it is also the mandatory model for
all Lexis testing and evaluation, chosen because it is cheap enough
for full repeated test rounds. Fase 3 adds the two things the
research requires: a fallback chain
built from the probe results (models that answered the probe, chat
models only), and an Auto router that picks per task. Cost per
finished task is recorded by the pulse in the ledger; compass reads
it back to compare models honestly (tokens are estimates at 4
characters per token, seconds are measured).
"""

import os
import re

MODELS = [
    "qwen3.7-plus",
    "gemini-3.1-pro",
    "gemini-nano-banana-2.1",
    "deepseek-v4-pro",
    "deepseek-v4.1-flash-1017-abliterated",
    "deepseek-v4.1-flash-1017-fast",
    "deepseek-v4.1-flash-uncensored",
    "gemini-3.8-flash",
    "deepseek-v4-pro-uncensored",
    "deepseek-v4.1-flash",
    "muse-wonder",
    "gemini-4-argon",
    "deepseek-v4.1-flash-abliterated",
    "deepseek-v4.1-flash-1017-uncensored",
    "muse-spark-1.3",
    "deepseek-v4-pro-abliterated",
    "gemini-3.1-flash-lite-image",
    "gemini-3-pro-image",
    "deepseek-v4-flash",
    "beam-1-0",
    "nano-banana-2",
]

DEFAULT_MODEL = "deepseek-v4.1-flash-1017-fast"
DEEP_MODEL = "deepseek-v4-pro"
MAX_ATTEMPTS = 4

_PROBE_LINE = re.compile(r"^([^:]+):\s+(OK|ERR|HTTP \d+)")
_IMAGE_HINTS = ("image", "banana")
_CODE_HINTS = ("```", "def ", "class ", "function ", "error",
               "traceback", "bug", "refactor", "compile")


def is_chat_model(name: str) -> bool:
    return not any(h in name for h in _IMAGE_HINTS)


def load_probe(root):
    """Parse probe_result.txt ('model: OK -> ...' per line) into a
    {model: answered} map. Missing file means no probe data."""
    probe = {}
    if not root:
        return probe
    path = os.path.join(root, "probe_result.txt")
    if not os.path.isfile(path):
        return probe
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _PROBE_LINE.match(line.strip())
            if m:
                probe[m.group(1).strip()] = m.group(2) == "OK"
    return probe


class Compass:
    """Holds the active model, the Auto flag, the probe results, and
    resolves user selections exactly like the original CLI."""

    def __init__(self, root=None) -> None:
        self.root = root
        self.current = DEFAULT_MODEL
        self.auto = False
        self.probe = load_probe(root)
        self.models = list(MODELS)
        self.catalog_source = "builtin"
        self.refresh_models()

    def refresh_models(self) -> int:
        """Rebuild the catalog from the active provider's own
        model list (Master's bug, 2026-11-11: a provider added
        in-session never had its models read, and the old model
        kept being used). Runs at startup and right after every
        provider change, so a new provider is usable in the
        same session. An unreadable endpoint keeps the current
        catalog; a current model the new provider does not
        serve is replaced by that provider's first model."""
        if not self.root:
            return len(self.models)
        try:
            from . import bridge

            ids = bridge.fetch_models(self.root)
            legacy = bool(
                bridge.active_provider(self.root).get("legacy"))
        except Exception:
            ids, legacy = None, True
        if ids:
            chat = [m for m in ids if is_chat_model(m)]
            self.models = chat or list(ids)
            self.catalog_source = "provider"
            if self.current not in self.models:
                self.current = self.models[0]
        elif legacy:
            self.models = list(MODELS)
            self.catalog_source = "builtin"
            if self.current not in self.models:
                self.current = DEFAULT_MODEL
        else:
            self.catalog_source = "provider-failed"
        return len(self.models)

    def list_models(self):
        return list(self.models)

    def select(self, choice: str) -> bool:
        """Resolve a /model choice: a 1-based number or an exact model
        name, as the original. Returns True on change."""
        choice = (choice or "").strip()
        if choice.lower() == "auto":
            self.auto = True
            return True
        if choice.isdigit() and 1 <= int(choice) <= len(self.models):
            self.current = self.models[int(choice) - 1]
            self.auto = False
            return True
        if choice in self.models:
            self.current = choice
            self.auto = False
            return True
        return False

    def answered(self, model: str) -> bool:
        """Did the probe prove this model answers? Unknown models are
        given the benefit of the doubt; probed failures are not."""
        return self.probe.get(model, True)

    def chain(self, start=None):
        """The attempt order for one task: the start model, then the
        probed chat models in catalog order. Capped at MAX_ATTEMPTS."""
        first = start or self.current
        order = [first]
        for m in self.models:
            if len(order) >= MAX_ATTEMPTS:
                break
            if m != first and is_chat_model(m) and self.answered(m):
                order.append(m)
        return order

    def backup_name(self, start=None):
        """The next model a task would fall back to, or None."""
        order = self.chain(start)
        return order[1] if len(order) > 1 else None

    def route(self, task_text: str) -> str:
        """Pick the model for one task. With Auto off this is simply
        the active model. With Auto on: long or code-shaped tasks go
        to the deep model, everything else to the fast default."""
        if not self.auto:
            return self.current
        text = task_text or ""
        deep = (
            len(text) > 600
            or any(h in text for h in _CODE_HINTS)
        )
        if deep and DEEP_MODEL in self.models \
                and self.answered(DEEP_MODEL):
            return DEEP_MODEL
        if DEFAULT_MODEL in self.models:
            return DEFAULT_MODEL
        return self.current

    @staticmethod
    def cost_summary(ledger):
        """Cost per finished task, aggregated per model from the
        ledger's cost records: tasks, completion rate, average
        seconds, average estimated tokens."""
        agg = {}
        for row in ledger.cost_rows():
            slot = agg.setdefault(row.get("model", "?"), {
                "tasks": 0, "done": 0, "seconds": 0.0, "tokens": 0,
            })
            slot["tasks"] += 1
            if row.get("outcome") == "done":
                slot["done"] += 1
            slot["seconds"] += float(row.get("seconds", 0.0))
            slot["tokens"] += int(row.get("prompt_tokens_est", 0)) + int(
                row.get("reply_tokens_est", 0)
            )
        for slot in agg.values():
            n = max(slot["tasks"], 1)
            slot["avg_seconds"] = round(slot["seconds"] / n, 2)
            slot["avg_tokens"] = int(slot["tokens"] / n)
            slot["done_rate"] = round(slot["done"] / n, 2)
        return agg
