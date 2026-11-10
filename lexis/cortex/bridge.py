# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Bridge: connection to the model provider (OpenAI-compatible endpoint).

Secrets come only from the project .env file and are never logged,
stored in the ledger, or placed in model context.
"""

import json
import os
import re

import requests
from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
KEY_ENV = "DEEPSEEK_API_KEY"
BASE_ENV = "DEEPSEEK_BASE_URL"

PROVIDERS_FILE = "providers.json"
LEGACY_NAME = "Osvyn"

_ROOT = None


def find_home(module_file: str = __file__) -> str:
    """Resolve the Lexis home folder (where .env, config and data live).

    The package can run from a source checkout or from an installed
    copy (site-packages), so the home cannot be derived from the
    module path alone. Order: the LEXIS_HOME override; the current
    folder when it is a Lexis home (holds config/ or .env); the
    source tree when running from a checkout; otherwise the current
    folder, where first-run setup creates what it needs.
    """
    override = os.getenv("LEXIS_HOME", "").strip()
    if override:
        return override
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "config")) or os.path.exists(
        os.path.join(cwd, ".env")
    ):
        return cwd
    tree = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(module_file)))
    )
    if os.path.isdir(os.path.join(tree, "config")):
        return tree
    return cwd


def load_env(root: str) -> None:
    global _ROOT
    _ROOT = root
    load_dotenv(os.path.join(root, ".env"))


# --- Providers -----------------------------------------------------
# Any number of providers, no whitelist (Master, 2026-11-10): the
# list lives in providers.json in the profile home; API keys live
# only in the profile .env, one variable per provider, and are
# never written to providers.json, the ledger, or any display.
# Without providers.json the original single-endpoint setup (the
# legacy entry) applies unchanged.

def _providers_path(root: str) -> str:
    return os.path.join(root, PROVIDERS_FILE)


def _load_providers(root: str):
    try:
        with open(_providers_path(root), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(
            data.get("providers"), list
        ):
            return data
    except Exception:
        pass
    return None


def _ensure_data(root: str):
    data = _load_providers(root)
    if data is None:
        data = {
            "active": LEGACY_NAME,
            "providers": [{"name": LEGACY_NAME, "legacy": True}],
        }
    return data


def _save_providers(root: str, data) -> None:
    with open(_providers_path(root), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def list_providers(root: str):
    data = _load_providers(root)
    if not data:
        return [{"name": LEGACY_NAME, "legacy": True}]
    out = [p for p in data["providers"]
           if isinstance(p, dict) and p.get("name")]
    return out or [{"name": LEGACY_NAME, "legacy": True}]


def active_provider(root: str):
    data = _load_providers(root)
    if data:
        for p in data["providers"]:
            if isinstance(p, dict) and p.get("name") == data.get("active"):
                return p
    return {"name": LEGACY_NAME, "legacy": True}


def provider_name(root: str) -> str:
    return active_provider(root).get("name", LEGACY_NAME)


def set_active_provider(root: str, name: str) -> bool:
    data = _ensure_data(root)
    if name not in [p.get("name") for p in data["providers"]]:
        return False
    data["active"] = name
    _save_providers(root, data)
    return True


def key_env_for(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return f"LEXIS_PROVIDER_{slug}_KEY"


def _set_env_value(root: str, var: str, value: str) -> None:
    path = os.path.join(root, ".env")
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    lines = [ln for ln in lines if not ln.startswith(var + "=")]
    lines.append(f"{var}={value}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def add_provider(root: str, name: str, base: str, key: str) -> None:
    """Register a provider and make it active. The key goes to the
    profile .env under its own variable; providers.json stores
    only the name, the base URL, and the variable's name."""
    data = _ensure_data(root)
    env_name = key_env_for(name)
    entry = {
        "name": name,
        "base": base.rstrip("/"),
        "key_env": env_name,
    }
    data["providers"] = [
        p for p in data["providers"] if p.get("name") != name
    ]
    data["providers"].append(entry)
    data["active"] = name
    _save_providers(root, data)
    if key:
        _set_env_value(root, env_name, key)


def current_key(root: str) -> str:
    """Re-read the key before each request, like the original main.py."""
    load_dotenv(os.path.join(root, ".env"), override=True)
    active = active_provider(root)
    if active.get("legacy"):
        return os.getenv(KEY_ENV, "")
    return os.getenv(active.get("key_env", ""), "")


def base_url(root: str = None) -> str:
    root = root if root is not None else _ROOT
    if root is not None:
        active = active_provider(root)
        if not active.get("legacy") and active.get("base"):
            return active["base"]
    return os.getenv(BASE_ENV, DEFAULT_BASE_URL)


def stream_chat(model: str, messages, api_key: str):
    """Yield content deltas from a streaming chat completion.

    Parses server-sent events exactly like the original main.py:
    lines starting with 'data: ', '[DONE]' ends the stream, and each
    JSON chunk contributes choices[0].delta.content when present.
    """
    url = f"{base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {"model": model, "messages": messages, "stream": True}
    response = requests.post(url, headers=headers, json=data, stream=True)
    for line in response.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8")
        if not decoded.startswith("data: "):
            continue
        data_str = decoded[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if "choices" in chunk and len(chunk["choices"]) > 0:
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content
