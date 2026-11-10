"""Dropped-file attachments: module seam + one Visor flow test.

The module is stdlib-only, so these tests also run off the PC.
The Visor test uses the same fake-stream seam as test_visor.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lexis.cortex import attachments  # noqa: E402


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, content, binary=False):
        path = self.root / name
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def test_plain_path_detected_prose_ignored(self):
        f = self._write("notes.txt", "hello world\nsecond line\n")
        found = attachments.find_dropped_paths(f"please read {f} now")
        self.assertEqual([f], found)
        self.assertEqual(
            [], attachments.find_dropped_paths("no files here at all")
        )
        self.assertEqual(
            [], attachments.find_dropped_paths("read C:\\nope\\missing.txt")
        )

    def test_unquoted_spaced_path_beats_existing_prefix_file(self):
        # Regression (System Creation, 2026-11-10): on a machine
        # whose profile folder contains a space, the first word
        # of an unquoted dropped path can itself be an existing
        # file. The scanner must attach the dropped file, never
        # that prefix stranger.
        sub = self.root / "a b"
        sub.mkdir()
        target = sub / "f.txt"
        target.write_text("real content\n", encoding="utf-8")
        (self.root / "a").write_text("stranger\n", encoding="utf-8")
        found = attachments.find_dropped_paths(f"read {target} now")
        self.assertEqual([target], found)
        (att,) = attachments.scan(f"read {target} now")
        self.assertIn("real content", att.model_block())

    def test_quoted_path_with_spaces_and_dedupe(self):
        sub = self.root / "my folder"
        sub.mkdir()
        f = sub / "a file.py"
        f.write_text("print('x')\n", encoding="utf-8")
        text = f'"{f}" and again {f}'
        found = attachments.find_dropped_paths(text)
        self.assertEqual(1, len(found))
        self.assertEqual("a file.py", found[0].name)

    def test_text_attachment_inlines_content(self):
        f = self._write("code.py", "x = 41\nprint(x + 1)\n")
        (att,) = attachments.scan(str(f))
        self.assertEqual("text", att.kind)
        self.assertEqual(2, att.lines)
        self.assertFalse(att.truncated)
        block = att.model_block()
        self.assertIn("x = 41", block)
        self.assertIn("Attached file: code.py", block)
        self.assertIn("code.py", att.card_text())

    def test_long_file_truncates_with_honest_note(self):
        body = "\n".join(f"line {i}" for i in range(900)) + "\n"
        f = self._write("big.log", body)
        (att,) = attachments.scan(str(f))
        self.assertTrue(att.truncated)
        self.assertEqual(900, att.lines)
        block = att.model_block()
        self.assertIn("line 499", block)
        self.assertNotIn("line 800", block)
        self.assertIn("Truncated", block)
        self.assertIn("900 lines total", block)
        self.assertIn("first 500 lines attached", att.card_text())

    def test_sensitive_file_content_never_inlined(self):
        f = self._write(".env", "SOME_KEY=do-not-leak-this\n")
        (att,) = attachments.scan(str(f))
        self.assertEqual("sensitive", att.kind)
        block = att.model_block()
        self.assertNotIn("do-not-leak-this", block)
        self.assertIn("content withheld", att.card_text())
        key = self._write("server.key", "do-not-leak-this either\n")
        (att2,) = attachments.scan(str(key))
        self.assertEqual("sensitive", att2.kind)

    def test_image_is_reference_only(self):
        f = self._write("shot.png", b"\x89PNG\r\n\x1a\nxxxx", binary=True)
        (att,) = attachments.scan(str(f))
        self.assertEqual("image", att.kind)
        self.assertIn("reference only", att.card_text())
        self.assertIn("text-only", att.model_block())

    def test_binary_is_reference_only(self):
        f = self._write("blob.bin", b"\x00\x01\x02\x03", binary=True)
        (att,) = attachments.scan(str(f))
        self.assertEqual("binary", att.kind)
        self.assertIn("Binary file", att.model_block())

    def test_enrich_appends_blocks_after_owner_words(self):
        f = self._write("a.txt", "CONTENT-9\n")
        atts = attachments.scan(f"look at {f}")
        out = attachments.enrich(f"look at {f}", atts)
        self.assertTrue(out.startswith(f"look at {f}"))
        self.assertIn("CONTENT-9", out)
        self.assertEqual("plain", attachments.enrich("plain", []))


class VisorAttachmentTest(unittest.IsolatedAsyncioTestCase):
    async def test_dropped_file_card_and_content_reach_model(self):
        import asyncio

        from lexis.cortex import bridge
        from lexis.visor.app import LexisVisor

        async def wait_for(pred, timeout=20.0):
            waited = 0.0
            while waited < timeout:
                if pred():
                    return True
                await asyncio.sleep(0.1)
                waited += 0.1
            return pred()

        seen = []
        orig = bridge.stream_chat

        def fake(model, messages, key):
            seen.append(messages)
            yield "got it"

        bridge.stream_chat = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                dropped = Path(d) / "drop me.py"
                dropped.write_text(
                    "MARKER_CONTENT_77 = True\n", encoding="utf-8"
                )
                app = LexisVisor(root=d)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text(f'summarize "{dropped}" please')
                    self.assertTrue(
                        await wait_for(lambda: not app.busy),
                        "turn did not finish",
                    )
                    await pilot.pause()
                    cards = app.query(".attach")
                    self.assertEqual(1, len(cards))
                    self.assertIn(
                        "drop me.py", str(cards[0].render())
                    )
                    flat = str(seen)
                    self.assertIn("MARKER_CONTENT_77", flat)
                    self.assertIn("Attached file: drop me.py", flat)
        finally:
            bridge.stream_chat = orig


if __name__ == "__main__":
    unittest.main()
