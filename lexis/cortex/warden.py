# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Warden: the permission gate and the compliance ladder.

Modes (shown to the user only by their ladder names):
- EMBER (Guardian): Lexis judges first; risky actions ask,
  every time.
- BLAZE (Loyal): warns once per risk class, then the owner's
  word stands: after the owner confirms past the one warning,
  later actions of the same class in this session proceed
  without asking (Master, 2026-11-11: the modes must be
  proven behavior, not product copy).
- INFERNO (Full compliance): the owner's word is law; no
  asking. Entry is a deliberate act on the surfaces (the
  Inferno screen), never a silent default here.

File reads never ask. Plan drafting denies writes and
execution at the tool level in every mode.
"""

MODES = ("EMBER", "BLAZE", "INFERNO")

ALLOW = "allow"
ASK = "ask"
WARN = "warn"
DENY = "deny"


class Warden:
    def __init__(self, mode: str = "EMBER") -> None:
        mode = (mode or "EMBER").upper()
        self.mode = mode if mode in MODES else "EMBER"
        # Plan mode (Fase 3): while a plan is being drafted, writes
        # are denied at the tool level in every compliance mode.
        self.planning = False
        # BLAZE memory: risk classes the owner has already been
        # warned about and confirmed in this session.
        self._warned = set()

    def set_mode(self, mode: str) -> None:
        """Switch mode. The BLAZE warning memory resets: a fresh
        mode means the owner gets the one warning again."""
        mode = (mode or "EMBER").upper()
        self.mode = mode if mode in MODES else "EMBER"
        self._warned = set()

    def note_warned(self, risk: str) -> None:
        """Record that the owner confirmed past the one BLAZE
        warning for this risk class."""
        self._warned.add(risk)

    def decide(self, risk: str) -> str:
        """risk is 'read', 'write', or 'exec' (the full toolset).
        Executing is gated exactly like writing: plan drafting
        denies it in every mode, INFERNO allows it, EMBER asks,
        BLAZE warns once per class and then allows."""
        if risk == "read":
            return ALLOW
        if risk in ("write", "exec"):
            if self.planning:
                return DENY
            if self.mode == "INFERNO":
                return ALLOW
            if self.mode == "BLAZE":
                if risk in self._warned:
                    return ALLOW
                return WARN
            return ASK
        return ASK
