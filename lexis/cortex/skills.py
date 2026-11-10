# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Skills: the agentskills.io registry for Lexis.

A skill is a folder with a SKILL.md (YAML frontmatter: name,
description, version). Disclosure is progressive: the session
catalog carries only names and descriptions; a skill's full body
enters the conversation only when the model asks for it with
[USE_SKILL: slug].

Safety contract (locked design, Master 2026-11-10): a skill is
ACTIVE only after it passes the security scan and its content
hash is pinned. If a pinned file changes, the skill drops back
to pending until it is scanned again; a skill that fails the
scan never activates. Draft skills (written by Lexis itself,
see evolve) additionally need the evidence gate and the owner.
"""

import hashlib
import json
import os
import re

SKILL_FILE = "SKILL.md"
PINS_FILE = ".pins.json"

# Focused denylist for skill bodies: instructions that would turn
# a text file into an attack. A hit never activates the skill.
SCAN_RULES = (
    ("pipe-to-shell", re.compile(r"(curl|wget)\b[^|\n]*\|\s*(sh|bash|powershell)", re.I)),
    ("download-exec", re.compile(r"Invoke-Expression|iex\s*\(|eval\(|exec\(", re.I)),
    ("secret-reading", re.compile(r"read.*(\.env|credentials|id_rsa|\.pem|\.key)\b", re.I)),
    ("env-dump", re.compile(r"(print|echo|cat|send|post)[^\n]*(environ|getenv)", re.I)),
    ("destructive-root", re.compile(r"rm\s+-rf\s+/|format\s+[a-z]:|del\s+/[sq]", re.I)),
    ("exfiltration", re.compile(r"(send|post|upload)[^\n]*(api[_-]?key|token|secret|password)", re.I)),
)


def scan_body(body: str):
    """Return the list of scan rule names the body violates."""
    return [name for name, rx in SCAN_RULES if rx.search(body)]


def parse_skill(text: str):
    """Parse the frontmatter subset (name, description, version)
    plus the body. Returns None when the header is unusable."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    header = text[3:end]
    fields = {}
    for line in header.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip().strip('"')
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or not description:
        return None
    return {
        "name": name,
        "description": description,
        "version": fields.get("version", "1"),
        "body": text[end + 4:].strip(),
    }


class SkillRegistry:
    def __init__(self, root: str, ledger=None):
        self.root = root
        self.dir = os.path.join(root, "skills")
        self.ledger = ledger
        self.skills = {}  # slug -> record
        self.refresh()

    # -- storage ----------------------------------------------------

    def _pins_path(self) -> str:
        return os.path.join(self.dir, PINS_FILE)

    def _load_pins(self) -> dict:
        try:
            with open(self._pins_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_pins(self, pins: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._pins_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pins, f, indent=1, sort_keys=True)
        os.replace(tmp, self._pins_path())

    def _event(self, text: str) -> None:
        if self.ledger is not None:
            try:
                self.ledger.append_event(0, "skills", text)
            except Exception:
                pass

    # -- lifecycle ----------------------------------------------------

    def refresh(self) -> None:
        """Rescan the skills folder against the pins. A skill is
        active only when its hash matches a pin that passed the
        scan; anything new or changed goes back through the gate.
        Bundled skills (shipped with Lexis) activate automatically
        on a clean scan; all others wait for explicit approval."""
        pins = self._load_pins()
        found = {}
        if os.path.isdir(self.dir):
            for slug in sorted(os.listdir(self.dir)):
                path = os.path.join(self.dir, slug, SKILL_FILE)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError:
                    continue
                parsed = parse_skill(text)
                if parsed is None:
                    continue
                digest = hashlib.sha256(
                    text.encode("utf-8")).hexdigest()
                findings = scan_body(parsed["body"])
                pin = pins.get(slug)
                status = "pending"
                if findings:
                    status = "blocked"
                elif pin and pin.get("sha256") == digest:
                    status = pin.get("status", "pending")
                found[slug] = {
                    "slug": slug, "path": path, "sha256": digest,
                    "findings": findings, "status": status,
                    **parsed,
                }
        self.skills = found

    def activate_bundled(self, bundled_slugs) -> None:
        """Pin and activate bundled skills whose scan is clean.
        Anything with findings stays blocked and is reported."""
        pins = self._load_pins()
        changed = False
        for slug in bundled_slugs:
            rec = self.skills.get(slug)
            if rec is None or rec["status"] == "blocked":
                continue
            if pins.get(slug, {}).get("sha256") != rec["sha256"] or \
                    rec["status"] != "active":
                pins[slug] = {
                    "sha256": rec["sha256"],
                    "version": rec["version"],
                    "status": "active",
                    "source": "bundled",
                }
                rec["status"] = "active"
                changed = True
                self._event(f"skill active: {slug} v{rec['version']}")
        if changed:
            self._save_pins(pins)

    def approve(self, slug: str, source: str = "owner") -> bool:
        """Owner (or gate) approval for a non-bundled skill whose
        scan is clean: pin its current hash and activate it."""
        rec = self.skills.get(slug)
        if rec is None or rec["status"] == "blocked":
            return False
        pins = self._load_pins()
        pins[slug] = {
            "sha256": rec["sha256"], "version": rec["version"],
            "status": "active", "source": source,
        }
        self._save_pins(pins)
        rec["status"] = "active"
        self._event(f"skill approved: {slug} v{rec['version']}")
        return True

    def status_of(self, slug: str):
        rec = self.skills.get(slug)
        return rec["status"] if rec else None

    # -- use ------------------------------------------------------------

    def active(self):
        return [r for r in self.skills.values()
                if r["status"] == "active"]

    def catalog_text(self) -> str:
        act = self.active()
        if not act:
            return ""
        lines = [
            "[SISTEM: Skill Lexis yang aktif. Saat tugas cocok "
            "dengan deskripsi skill, muat isinya dulu dengan "
            "[USE_SKILL: slug] lalu ikuti isinya.]"
        ]
        for rec in sorted(act, key=lambda r: r["slug"]):
            lines.append(f"- {rec['slug']}: {rec['description']}")
        return "\n".join(lines)

    def load_body(self, slug: str):
        rec = self.skills.get(slug)
        if rec is None or rec["status"] != "active":
            return None
        return rec["body"]


def bundled_library_dir() -> str:
    """The skill library shipped inside the package."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "skill_library",
    )


def sync_bundled(root: str):
    """Copy the bundled tier library into the profile's skills
    folder (only skills that are missing there; an owner's edited
    copy is never overwritten). Returns the bundled slug list."""
    src_root = bundled_library_dir()
    slugs = []
    if not os.path.isdir(src_root):
        return slugs
    for slug in sorted(os.listdir(src_root)):
        src = os.path.join(src_root, slug, SKILL_FILE)
        if not os.path.isfile(src):
            continue
        slugs.append(slug)
        dst = os.path.join(root, "skills", slug, SKILL_FILE)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, "r", encoding="utf-8") as f:
                content = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
    return slugs
