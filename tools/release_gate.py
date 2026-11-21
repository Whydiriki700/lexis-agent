# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""The public-release gate (Master's hard rule, 2026-11-10:
the public Lexis repository must never contain a paid
file, a key, or a credential, and this check must run
before any release).

Run from the repository root before a push that will be
public, before a visibility change, and before a PyPI
build:

    python tools/release_gate.py

Exit code 0 means the gate passed. Any failure prints the
offending files and exits 1; a failure is a stop, not a
warning. The gate checks four things:

1. No private or paid path is tracked by git (the
   jailbreak layer, credential files, the provider list,
   the memory store, key material).
2. No tracked file's content carries a credential-shaped
   string (provider keys, platform tokens, private keys).
3. Every private path is covered by .gitignore, so it
   cannot wander in later by accident.
4. The generated persona module exists, so the package
   being released is the one that actually runs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

PRIVATE_PATHS = (
    "config/JAILBREAK.md",
    ".env",
    "providers.json",
    "visor_prefs.json",
    "lexis_data/state.db",
    "skills/.pins.json",
)

PRIVATE_SUFFIXES = (".pem", ".key", ".p12", ".db")

SECRET_PATTERNS = (
    ("provider key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("assigned secret",
     re.compile(r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret)"
                r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']")),
)


def _git(*args) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True,
        check=True)
    return out.stdout


def main() -> int:
    root = _git("rev-parse", "--show-toplevel").strip()
    os.chdir(root)
    tracked = [p for p in _git("ls-files").splitlines() if p]
    failures = []

    for path in tracked:
        if path in PRIVATE_PATHS or path.endswith(PRIVATE_SUFFIXES):
            failures.append(f"private path tracked: {path}")

    for path in tracked:
        try:
            with open(path, encoding="utf-8",
                      errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for label, rx in SECRET_PATTERNS:
            if rx.search(text):
                failures.append(
                    f"credential-shaped content ({label}): {path}")

    for path in PRIVATE_PATHS:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", path])
        if proc.returncode != 0:
            failures.append(f"private path not ignored: {path}")

    if not os.path.isfile(
            os.path.join("lexis", "cortex", "persona_data.py")):
        failures.append(
            "lexis/cortex/persona_data.py is missing: run "
            "tools/gen_persona.py before building a release")

    if failures:
        print("RELEASE GATE: FAIL")
        for line in failures:
            print(" -", line)
        return 1
    print(f"RELEASE GATE: PASS ({len(tracked)} tracked files, "
          "no private paths, no credential-shaped content, "
          "persona module present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
