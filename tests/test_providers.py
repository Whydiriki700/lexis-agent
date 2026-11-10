# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Bug 1 (Master, 2026-11-11): a provider added in-session
must have its models read, and the old model must not keep
being used. Bridge fetches the active provider's /models;
Compass builds its catalog from the active provider and
refreshes on every provider change.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexis.cortex import bridge  # noqa: E402
from lexis.cortex.compass import DEFAULT_MODEL, MODELS, Compass  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.error:
            raise self.error
        return _Resp(self.payload)


class BridgeFetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._old = bridge.requests
        self.addCleanup(setattr, bridge, "requests", self._old)

    def test_legacy_provider_reads_nothing(self):
        self.assertIsNone(bridge.fetch_models(self.tmp))

    def test_custom_provider_models_are_read(self):
        bridge.add_provider(
            self.tmp, "TestProv", "https://api.example/v1", "k-1")
        bridge.requests = _FakeRequests({"data": [
            {"id": "alpha-1"}, {"id": "beta-2"}, {"no-id": 1},
        ]})
        self.assertEqual(
            ["alpha-1", "beta-2"], bridge.fetch_models(self.tmp))
        self.assertTrue(
            bridge.requests.calls[0].endswith("/v1/models"))

    def test_unreadable_endpoint_returns_none(self):
        bridge.add_provider(
            self.tmp, "DownProv", "https://down.example/v1", "k-2")
        bridge.requests = _FakeRequests(error=OSError("down"))
        self.assertIsNone(bridge.fetch_models(self.tmp))


class CompassProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._old_fetch = bridge.fetch_models
        self.addCleanup(
            setattr, bridge, "fetch_models", self._old_fetch)

    def stub_fetch(self, ids):
        bridge.fetch_models = lambda root, timeout=6: ids

    def test_provider_catalog_replaces_the_builtin(self):
        bridge.add_provider(
            self.tmp, "TestProv", "https://api.example/v1", "k")
        self.stub_fetch(["alpha-1", "beta-2", "gamma-image-x"])
        compass = Compass(self.tmp)
        self.assertEqual(["alpha-1", "beta-2"], compass.list_models())
        self.assertEqual("provider", compass.catalog_source)
        # The old model is not served here: it must not linger.
        self.assertEqual("alpha-1", compass.current)
        self.assertFalse(compass.select(DEFAULT_MODEL))
        self.assertTrue(compass.select("beta-2"))
        self.assertEqual("beta-2", compass.current)
        self.assertEqual("beta-2", compass.chain()[0])

    def test_failed_read_keeps_the_current_catalog(self):
        bridge.add_provider(
            self.tmp, "DownProv", "https://down.example/v1", "k")
        self.stub_fetch(None)
        compass = Compass(self.tmp)
        self.assertEqual("provider-failed", compass.catalog_source)
        self.assertEqual(MODELS, compass.list_models())

    def test_switch_back_to_legacy_restores_the_builtin(self):
        bridge.add_provider(
            self.tmp, "TestProv", "https://api.example/v1", "k")
        self.stub_fetch(["alpha-1"])
        compass = Compass(self.tmp)
        self.assertEqual(["alpha-1"], compass.list_models())
        os.remove(os.path.join(self.tmp, "providers.json"))
        self.stub_fetch(None)  # the real fetch reads nothing
        compass.refresh_models()  # for the legacy provider
        self.assertEqual("builtin", compass.catalog_source)
        self.assertEqual(MODELS, compass.list_models())
        self.assertEqual(DEFAULT_MODEL, compass.current)


if __name__ == "__main__":
    unittest.main()
