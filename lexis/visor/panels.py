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


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"~{n / 1000:.1f}K"
    return f"~{n}"


def tokens_text(ledger, session_id, live_out_chars: int = 0,
                busy: bool = False) -> Text:
    """The realtime token dashboard (Master, 2026-11-10). The
    streaming-out counter moves while the model writes; the rest
    are this session's ledger cost rows. Every figure is the
    ledger's own 4-chars-per-token estimate, marked with ~."""
    in_total = out_total = 0
    last_in = last_out = None
    if ledger is not None and session_id is not None:
        import json

        rows = ledger._conn.execute(
            "SELECT detail FROM events WHERE session_id = ? "
            "AND kind = 'cost' ORDER BY id",
            (session_id,),
        ).fetchall()
        for (detail,) in rows:
            try:
                d = json.loads(detail)
            except ValueError:
                continue
            last_in = int(d.get("prompt_tokens_est", 0))
            last_out = int(d.get("reply_tokens_est", 0))
            in_total += last_in
            out_total += last_out
    out = Text()
    out.append("TOKENS", style=f"bold {DIM}")
    out.append("   live · estimates", style=FAINT)
    _kv(out, "Streaming out",
        _fmt_tokens(live_out_chars // 4) if busy else "—")
    _kv(out, "Last turn in",
        _fmt_tokens(last_in) if last_in is not None else "—")
    _kv(out, "Last turn out",
        _fmt_tokens(last_out) if last_out is not None else "—")
    _kv(out, "Session in", _fmt_tokens(in_total) if in_total else "—")
    _kv(out, "Session out",
        _fmt_tokens(out_total) if out_total else "—")
    _kv(out, "Session total",
        _fmt_tokens(in_total + out_total)
        if (in_total + out_total) else "—")
    return out


def _ctx_bar(pct: int, cells: int = 10) -> str:
    filled = max(0, min(cells, round(pct * cells / 100)))
    return "▓" * filled + "░" * (cells - filled)


def status_text(*, model, provider, mode, mode_icon, conn, state_icon,
                state_label, turn_in, turn_out, live, sess_total,
                ctx_pct, turn_secs, queued) -> Text:
    """The fixed status strip (Master, 2026-11-10): two lines that
    update in place and never print into the chat flow. Every value
    is live app state; token figures carry the ~ estimate mark."""
    out = Text(overflow="crop")
    out.append("Model ", style=DIM)
    out.append(str(model), style=f"bold {TXT}")
    out.append(" · Provider ", style=DIM)
    out.append(str(provider), style=f"bold {TXT}")
    out.append(" · ", style=DIM)
    out.append(f"{mode_icon} {mode}", style=f"bold {AMBER}")
    out.append(" · Link ", style=DIM)
    if conn == "linked":
        out.append("● linked", style=GREEN)
    elif conn == "error":
        out.append("● link error", style=RED)
    else:
        out.append("○ standby", style=FAINT)
    out.append(" · ", style=DIM)
    out.append(f"{state_icon} {state_label}", style=f"bold {EMBER}")
    out.append("\n")
    out.append("Turn ", style=DIM)
    if live:
        out.append(f"out {_fmt_tokens(turn_out)} live", style=TXT)
    elif turn_in is not None:
        out.append(
            f"in {_fmt_tokens(turn_in)} · out "
            f"{_fmt_tokens(turn_out or 0)}",
            style=TXT,
        )
    else:
        out.append("—", style=TXT)
    out.append(" · Session cost ", style=DIM)
    out.append(_fmt_tokens(sess_total) + " tokens" if sess_total else "—",
               style=TXT)
    out.append(" · Context ", style=DIM)
    out.append(f"{ctx_pct}% ", style=TXT)
    out.append(_ctx_bar(ctx_pct), style=EMBER)
    out.append(" · Turn time ", style=DIM)
    out.append(f"{turn_secs:.1f} s" if turn_secs is not None else "—",
               style=f"bold {TXT}")
    if queued:
        out.append(" · Queued ", style=DIM)
        out.append(str(queued), style=f"bold {AMBER}")
    out.append(" · Autosaved · resumable anytime", style=DIM)
    return out


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
