# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Compass: model catalog and selection for Lexis.

Fase 1 keeps the exact catalog and default of the original main.py.
Automatic routing by cost per finished task and probe-driven fallback
arrive in Fase 3; the probe results in probe_result.txt are the seed data.
"""

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

DEFAULT_MODEL = "deepseek-v4.1-flash-uncensored"


class Compass:
    """Holds the active model and resolves user selections."""

    def __init__(self) -> None:
        self.current = DEFAULT_MODEL

    def list_models(self):
        return list(MODELS)

    def select(self, choice: str) -> bool:
        """Resolve a /model choice exactly like the original CLI:
        a 1-based number or an exact model name. Returns True on change."""
        choice = (choice or "").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(MODELS):
            self.current = MODELS[int(choice) - 1]
            return True
        if choice in MODELS:
            self.current = choice
            return True
        return False
