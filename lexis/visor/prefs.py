"""Per-profile Visor preferences (Master, 2026-11-11).

Presentation choices live in visor_prefs.json in the profile
home, beside providers.json, and follow the same house rule
as the provider list: tolerant reads (a missing or damaged
file means defaults), plain JSON, and never any secret. The
file carries the terminal display mode and the theme choice;
both are presentation only and change nothing about how the
work itself runs or is journaled.
"""

from __future__ import annotations

import json
import os

PREFS_FILE = "visor_prefs.json"


def _path(root: str) -> str:
    return os.path.join(root, PREFS_FILE)


def load(root: str) -> dict:
    try:
        with open(_path(root), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def get(root: str, key: str, default=None):
    return load(root).get(key, default)


def set_pref(root: str, key: str, value) -> None:
    data = load(root)
    data[key] = value
    with open(_path(root), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
