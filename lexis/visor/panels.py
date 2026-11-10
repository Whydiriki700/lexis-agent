# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Rail panel content builders (pure functions over real state).

Every value shown comes from the live Cortex state: the vault
messages, the ledger in state.db, and the turn journal. Nothing is
invented; a value that cannot be measured yet shows a dash.
Labels use user language only, per the approved mockup.
"""

from rich.text import Text

EMBER = "#ff7a29"
AMBER = "#e0a83c"
GREEN = "#3fb96f"
RED = "#e05c5c"
TXT = "#e8ded2"
DIM = "#a08b74"
FAINT = "#6f5f4e"

CONTEXT_WINDOW = 128_000  # nominal window the percentage refers to
COMPACTION_AT = 82  # locked trigger ratio from the research


def _kv(out: Text, label: str, value: str, first: bool = False) -> None:
    if not first:
        out.append("\n")
    out.append(label.ljust(20), style=DIM)
    out.append(value, style=TXT)


def plan_text(steps) -> Text:
    """steps: list of (state, label); state in done/now/todo."""
    done = sum(1 for s, _ in steps if s == "done")
    out = Text()
    out.append("PLAN", style=f"bold {DIM}")
    if steps:
        out.append(f"   step {min(done + 1, len(steps))} of {len(steps)}",
                   style=FAINT)
    for state, label in steps:
        out.append("\n")
        if state == "done":
            out.append("✓ ", style=GREEN)
            out.append(label, style=TXT)
        elif state == "now":
            out.append("▸ ", style=EMBER)
            out.append(label, style=EMBER)
        else:
            out.append("· ", style=FAINT)
            out.append(label, style=DIM)
    if not steps:
        out.append("\n")
        out.append("No work in progress.", style=DIM)
    return out


def context_stats(messages):
    """Split the conversation into the mockup's context buckets.
    Tokens are estimated at 4 characters per token."""
    system = history = tools = 0
    for i, m in enumerate(messages):
        chars = len(m.get("content", ""))
        if i == 0 and m.get("role") == "system":
            system += chars
        elif m.get("content", "").startswith("[HASIL BACA FILE"):
            tools += chars
        else:
            history += chars
    est = lambda c: c / 4.0
    total = est(system + history + tools)
    pct = int(round(100 * total / CONTEXT_WINDOW)) if total else 0
    fmt = lambda v: f"{v / 1000:.1f}K" if v >= 1000 else f"{int(v)}"
    return {
        "pct": min(pct, 100),
        "system": fmt(est(system)),
        "history": fmt(est(history)),
        "tools": fmt(est(tools)),
    }


def context_text(messages) -> Text:
    s = context_stats(messages)
    out = Text()
    out.append("CONTEXT", style=f"bold {DIM}")
    out.append(f"   {s['pct']}%", style=FAINT)
    _kv(out, "System instructions", s["system"])
    _kv(out, "Session history", s["history"])
    _kv(out, "Tool output", s["tools"])
    _kv(out, "Prefix cache hit", "—")
    _kv(out, "Auto compaction", f"at {COMPACTION_AT}%")
    return out


def context_percent(messages) -> int:
    return context_stats(messages)["pct"]


def memory_text(ledger, session_id: int, documents) -> Text:
    conn = ledger._conn
    journal = conn.execute(
        "SELECT COUNT(*) FROM events WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    promises = ledger.fact_count(kind="decision") + ledger.fact_count(
        kind="promise"
    )
    out = Text()
    out.append("MEMORY", style=f"bold {DIM}")
    _kv(out, "Facts this session",
        str(ledger.fact_count(session_id=session_id)))
    _kv(out, "Facts in memory", str(ledger.fact_count()))
    _kv(out, "Episodes stored", str(ledger.session_count()))
    _kv(out, "Promises & decisions", str(promises))
    _kv(out, "Session journal", f"{journal} entries recorded")
    _kv(out, "Memory file",
        f"state.db · {len(documents)} MD files stored inside")
    _kv(out, "Your profile", "loaded" if "USER.md" in documents else "—")
    return out


def skills_text(ledger=None, session_id=None) -> Text:
    saved = None
    if ledger is not None and session_id is not None:
        import json

        total = 0
        rows = ledger._conn.execute(
            "SELECT detail FROM events WHERE session_id = ? "
            "AND kind = 'compaction'",
            (session_id,),
        ).fetchall()
        for (detail,) in rows:
            try:
                d = json.loads(detail)
                total += int(d.get("before_tokens", 0)) - int(
                    d.get("after_tokens", 0)
                )
            except ValueError:
                pass
        if total > 0:
            saved = f"~{total / 1000:.1f}K tokens by condensing"
    out = Text()
    out.append("SKILLS & SAVINGS", style=f"bold {DIM}")
    _kv(out, "Skills installed", "none yet")
    _kv(out, "Active this turn", "—")
    _kv(out, "Saved by memory", saved or "—")
    return out


MODE_LINES = {
    "EMBER": "Guardian · may hold a harmful order",
    "BLAZE": "Loyal · warns once, then your word stands",
    "INFERNO": "Full compliance · your word is law",
}


def mode_text(mode: str) -> Text:
    """The compliance ladder, shown permanently in the rail."""
    out = Text()
    out.append("COMPLIANCE", style=f"bold {DIM}")
    for name in ("EMBER", "BLAZE", "INFERNO"):
        out.append("\n")
        if name == mode:
            out.append("▸ ", style=EMBER)
            out.append(name, style=f"bold {RED if name == 'INFERNO' else AMBER}")
            out.append(f"  {MODE_LINES[name]}", style=TXT)
        else:
            out.append("· ", style=FAINT)
            out.append(name, style=DIM)
            out.append(f"  {MODE_LINES[name]}", style=FAINT)
    return out
