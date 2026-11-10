# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Prism: context assembly, budget, and compaction.

The context window is a budget. When the live conversation passes
the locked trigger ratio (82% of the nominal window), prism folds
the older middle of the conversation into one summary message.
Under the anti-forgetting doctrine, folding never happens first:
durable statements are extracted into the cold tier (vault facts)
before their raw text is condensed, and the system anchors (system
prompt and the few-shot pair) are never folded at all.
"""

import json

WINDOW = 128_000  # nominal context window the budget refers to
COMPACT_RATIO = 0.82  # locked trigger ratio from the research
ANCHORS = 3  # system prompt + few-shot pair: never folded


def estimate_tokens(messages) -> int:
    """Token estimate at 4 characters per token (the same estimator
    the Visor context panel shows, so the numbers agree)."""
    return sum(len(m.get("content", "")) for m in messages) // 4


def needs_compaction(messages, window: int = WINDOW,
                     ratio: float = COMPACT_RATIO) -> bool:
    return estimate_tokens(messages) > window * ratio


def compact(vault, ledger, session_id: int, keep_last: int = 6):
    """Fold the middle of the conversation into one summary message.

    Returns a report dict, or None when there is nothing worth
    folding. Facts are extracted from every folded message first;
    the summary keeps the first line of each folded message so the
    thread of the conversation survives in plain sight."""
    msgs = vault.messages()
    if len(msgs) <= ANCHORS + keep_last:
        return None
    folded = msgs[ANCHORS:len(msgs) - keep_last] if keep_last else msgs[ANCHORS:]
    kept = msgs[len(msgs) - keep_last:] if keep_last else []
    if not folded:
        return None

    facts = 0
    for m in folded:
        facts += vault.learn_from(ledger, session_id, m.get("content", ""))

    points = []
    for m in folded:
        first = (m.get("content", "").strip().splitlines() or [""])[0].strip()
        if first:
            points.append(first[:90])
    summary = (
        "[Earlier conversation condensed by Lexis to stay within the "
        f"context budget. {len(folded)} messages were folded; durable "
        "facts were stored in memory first. Key points: "
        + "; ".join(points)
        + "]"
    )
    before = estimate_tokens(msgs)
    new_messages = msgs[:ANCHORS] + [{"role": "user", "content": summary}] + kept
    after = estimate_tokens(new_messages)
    vault.replace_all(new_messages)
    ledger.append_event(session_id, "compaction", json.dumps({
        "folded": len(folded), "facts": facts,
        "before_tokens": before, "after_tokens": after,
    }))
    return {
        "folded": len(folded), "facts": facts,
        "before_tokens": before, "after_tokens": after,
    }
