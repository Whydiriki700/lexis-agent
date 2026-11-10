# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Bridge: connection to the model provider (OpenAI-compatible endpoint).

Secrets come only from the project .env file and are never logged,
stored in the ledger, or placed in model context.
"""

import json
import os

import requests
from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
KEY_ENV = "DEEPSEEK_API_KEY"
BASE_ENV = "DEEPSEEK_BASE_URL"


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
    load_dotenv(os.path.join(root, ".env"))


def current_key(root: str) -> str:
    """Re-read the key before each request, like the original main.py."""
    load_dotenv(os.path.join(root, ".env"), override=True)
    return os.getenv(KEY_ENV, "")


def base_url() -> str:
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
