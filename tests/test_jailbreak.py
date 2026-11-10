# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""config/JAILBREAK.md as a runtime source (Master's order,
2026-11-11): its text rides as its own system message right
after the persona prompt at bootstrap. The persona segment is
never altered, and without the file the opening is exactly
what it was before the order. Synthetic content only: the
real file is never read by tests.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexis.cortex import persona_data  # noqa: E402
from lexis.cortex.vault import Vault  # noqa: E402

SENTINEL = "SYNTHETIC JAILBREAK SEGMENT FOR TESTS ONLY\nline two\n"


def persona_hash():
    return hashlib.sha256(
        persona_data.SYSTEM_PROMPT.encode("utf-8")).hexdigest()


class JailbreakRuntimeTest(unittest.TestCase):
    def make_root(self, content=None, raw=None):
        root = tempfile.mkdtemp()
        cfg = os.path.join(root, "config")
        os.makedirs(cfg)
        if raw is not None:
            with open(os.path.join(cfg, "JAILBREAK.md"), "wb") as f:
                f.write(raw)
        elif content is not None:
            with open(os.path.join(cfg, "JAILBREAK.md"), "wb") as f:
                f.write(content.encode("utf-8"))
        return root

    def test_segment_rides_after_persona_before_fewshot(self):
        root = self.make_root(content=SENTINEL)
        msgs = Vault().bootstrap(root)
        self.assertEqual("system", msgs[0]["role"])
        self.assertEqual(
            persona_hash(),
            hashlib.sha256(
                msgs[0]["content"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual("system", msgs[1]["role"])
        self.assertEqual(SENTINEL, msgs[1]["content"])
        rest = msgs[2:]
        self.assertEqual(len(persona_data.FEWSHOT), len(rest))

    def test_no_root_keeps_the_old_opening(self):
        msgs = Vault().bootstrap()
        self.assertEqual(1 + len(persona_data.FEWSHOT), len(msgs))
        self.assertEqual(
            persona_hash(),
            hashlib.sha256(
                msgs[0]["content"].encode("utf-8")).hexdigest(),
        )

    def test_missing_file_keeps_the_old_opening(self):
        root = self.make_root()
        msgs = Vault().bootstrap(root)
        self.assertEqual(1 + len(persona_data.FEWSHOT), len(msgs))

    def test_undecodable_file_yields_no_segment(self):
        root = self.make_root(raw=b"\xff\xfe\x00bad")
        msgs = Vault().bootstrap(root)
        self.assertEqual(1 + len(persona_data.FEWSHOT), len(msgs))


if __name__ == "__main__":
    unittest.main()
