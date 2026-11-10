# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Warden: the permission gate and the compliance ladder.

Modes (shown to the user only by their ladder names):
- EMBER (Guardian): Lexis judges first; risky actions ask.
- BLAZE (Loyal): warns once, then the owner's word stands; in Fase 1
  this still asks, the warning text is the surface's job.
- INFERNO (Full compliance): the owner's word is law; no asking.

Fase 1 preserves the original behavior: file reads never ask,
file writes ask (the old y/n prompt) under EMBER and BLAZE.
"""

MODES = ("EMBER", "BLAZE", "INFERNO")

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


class Warden:
    def __init__(self, mode: str = "EMBER") -> None:
        mode = (mode or "EMBER").upper()
        self.mode = mode if mode in MODES else "EMBER"
        # Plan mode (Fase 3): while a plan is being drafted, writes
        # are denied at the tool level in every compliance mode.
        self.planning = False

    def decide(self, risk: str) -> str:
        """risk is 'read', 'write', or 'exec' (the full toolset).
        Executing is gated exactly like writing: plan drafting
        denies it in every mode, INFERNO allows it, the guarded
        modes ask."""
        if risk == "read":
            return ALLOW
        if risk in ("write", "exec"):
            if self.planning:
                return DENY
            if self.mode == "INFERNO":
                return ALLOW
            return ASK
        return ASK
