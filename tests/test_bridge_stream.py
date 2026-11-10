# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Bug 3, layer 2 (Master, 2026-11-11): the model stream
must carry a timeout, so a stalled connection raises and the
fallback chain can move instead of the turn hanging forever
in silence.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexis.cortex import bridge  # noqa: E402


class _Resp:
    def __init__(self):
        self.status_code = 200

    def iter_lines(self):
        yield b'data: {"choices": [{"delta": {"content": "halo"}}]}'
        yield b"data: [DONE]"


class _FakeRequests:
    def __init__(self):
        self.kwargs = None

    def post(self, url, headers=None, json=None, stream=None,
             timeout=None):
        self.kwargs = {"url": url, "timeout": timeout,
                       "stream": stream}
        return _Resp()


class StreamTimeoutTest(unittest.TestCase):
    def test_stream_carries_a_read_timeout(self):
        old = bridge.requests
        fake = _FakeRequests()
        bridge.requests = fake
        try:
            out = list(bridge.stream_chat("m", [], "key"))
        finally:
            bridge.requests = old
        self.assertEqual(["halo"], out)
        self.assertIsNotNone(fake.kwargs["timeout"])
        connect, read = fake.kwargs["timeout"]
        self.assertGreater(read, 0)
        self.assertEqual(bridge.STREAM_READ_TIMEOUT, read)


if __name__ == "__main__":
    unittest.main()
