# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Evolve: Lexis drafts a new skill from its own verified work
(Step 3, Master 2026-11-10/11: evolution must be proven, not
claimed).

The gates, in order, none of them skippable:

1. Evidence: the source session must hold a judge verdict of
   'pass' for the work being distilled. No verified success,
   no draft.
2. Authorship: the model writes the skill body; this module
   builds the frontmatter itself, so the evidence fields can
   never be forged by the drafting reply.
3. Security scan: the draft lands in the profile skills folder
   and the registry scans it like any other skill. Findings
   mean blocked, never active.
4. Owner: a clean draft waits as 'pending' until the owner
   approves it (registry.approve). Only then does it ride in
   the session catalog.
"""

import os
import re

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
DESC_MARKER = "[SKILL_DESC:"


def session_evidence(ledger, session_id: int):
    """(ok, evidence_text): ok when the session's judge events
    include at least one 'pass' verdict. The evidence text is
    the latest passing verdict, stored in the draft so a reader
    can see what success the skill was distilled from."""
    try:
        rows = ledger.events(session_id, kind="judge")
    except Exception:
        return False, ""
    passes = [r for r in rows if r.startswith("pass")]
    if not passes:
        return False, ""
    return True, passes[-1]


def split_draft(reply: str):
    """Split a drafting reply into (description, body). The
    reply must open with a [SKILL_DESC: ...] line; everything
    after it is the skill body. Returns (None, None) when the
    reply does not carry the marker."""
    if not reply:
        return None, None
    idx = reply.find(DESC_MARKER)
    if idx == -1:
        return None, None
    end = reply.find("]", idx)
    if end == -1:
        return None, None
    description = reply[idx + len(DESC_MARKER):end].strip()
    body = reply[end + 1:].strip()
    if not description or not body:
        return None, None
    return description, body


def build_draft_text(slug: str, description: str, body: str,
                     session_id: int, evidence: str) -> str:
    """The full SKILL.md for a draft. Frontmatter is built
    here, never by the model: name, description, version, and
    the provenance fields (source, session, evidence)."""
    header = (
        "---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        "version: 1\n"
        "source: evolve\n"
        f"source_session: {session_id}\n"
        f"evidence: {evidence}\n"
        "---\n\n"
    )
    return header + body.strip() + "\n"


def create_draft(root: str, registry, ledger, session_id: int,
                 slug: str, description: str, body: str,
                 evidence: str) -> dict:
    """Write a drafted skill into the profile and put it
    through the registry gate. Returns a result dict the
    surfaces can report verbatim."""
    if not SLUG_RE.match(slug or ""):
        return {"ok": False,
                "reason": "skill name must be lowercase letters, "
                          "digits and dashes"}
    if registry is None:
        return {"ok": False, "reason": "skill registry is not ready"}
    registry.refresh()
    if slug in registry.skills:
        return {"ok": False,
                "reason": f"a skill named {slug} already exists"}
    text = build_draft_text(slug, description, body,
                            session_id, evidence)
    path = os.path.join(root, "skills", slug, "SKILL.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    registry.refresh()
    rec = registry.skills.get(slug)
    if rec is None:
        return {"ok": False,
                "reason": "the draft could not be parsed as a skill"}
    if ledger is not None:
        try:
            ledger.append_event(
                session_id, "evolve",
                f"draft {slug} from session {session_id}: "
                f"{rec['status']}",
            )
        except Exception:
            pass
    return {
        "ok": True,
        "slug": slug,
        "status": rec["status"],
        "findings": rec["findings"],
        "path": path,
    }
