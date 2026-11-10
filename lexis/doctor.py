# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""lexis doctor: installation health check.

Reports the state of the install in user language and returns an exit
code (0 healthy, 1 problems found). Never prints secret values; the
.env file is reported by presence only.
"""

import os
import platform
import sys

import lexis
from lexis.cortex import bridge

ROOT = bridge.find_home()


def _check(label, ok, detail=""):
    mark = "ok" if ok else "PROBLEM"
    line = f"[{mark}] {label}"
    if detail:
        line += f": {detail}"
    print(line)
    return ok


def run() -> int:
    print(f"Lexis doctor (Lexis Agent {lexis.__version__})")
    healthy = True

    py_ok = sys.version_info >= (3, 10)
    healthy &= _check(
        "Python", py_ok,
        f"{platform.python_version()} on {platform.system()}",
    )
    healthy &= _check("Project folder", os.path.isdir(ROOT), ROOT)

    cfg = os.path.join(ROOT, "config")
    cfg_ok = os.path.isdir(cfg)
    count = 0
    if cfg_ok:
        count = len([n for n in os.listdir(cfg) if n.endswith(".md")])
    healthy &= _check(
        "Configuration folder", cfg_ok and count > 0,
        f"{count} documents" if cfg_ok else "missing",
    )

    env_path = os.path.join(ROOT, ".env")
    healthy &= _check(
        "Provider settings file", os.path.isfile(env_path),
        "present (contents never shown)" if os.path.isfile(env_path)
        else "missing",
    )

    for mod, label in (("requests", "HTTP library"),
                       ("dotenv", "Settings loader")):
        try:
            __import__(mod)
            ok, detail = True, "installed"
        except ImportError:
            ok, detail = False, "not installed"
        healthy &= _check(label, ok, detail)

    data_dir = os.path.join(ROOT, "lexis_data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        probe = os.path.join(data_dir, ".doctor_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        writable = True
    except OSError:
        writable = False
    healthy &= _check("Session storage", writable, data_dir)

    print("Result:", "healthy" if healthy else "problems found, see above")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(run())
