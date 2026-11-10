# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Fase 1 verification suite for Lexis (stdlib unittest, no network).

Run from the project root:  python -m unittest discover -s tests -v

Proves: persona byte-fidelity against main.py, model catalog fidelity,
thinking-filter parity, forge registry and marker parsing, warden gate,
ledger persistence, vault bootstrap, and the pulse turn flow against a
fake stream (plain reply, file read, file write allowed and denied).
Persona content is only ever compared by hash or equality, never printed.
"""

import ast
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def extract_main():
    src = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    system_prompt, models, default, fewshot = None, None, None, []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", "")
            if name == "system_prompt":
                system_prompt = ast.literal_eval(node.value)
            elif name == "MODELS":
                models = ast.literal_eval(node.value)
            elif name == "current_model":
                default = ast.literal_eval(node.value)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "append"
                and getattr(func.value, "id", "") == "messages"
                and node.value.args
            ):
                d = ast.literal_eval(node.value.args[0])
                if isinstance(d, dict) and "role" in d:
                    fewshot.append((d["role"], d["content"]))
    return system_prompt, models, default, fewshot


class TestFidelity(unittest.TestCase):
    def test_persona_byte_identical(self):
        sp, _, _, fs = extract_main()
        from lexis.cortex import persona_data

        self.assertEqual(persona_data.SYSTEM_PROMPT, sp)
        self.assertEqual([tuple(x) for x in persona_data.FEWSHOT], fs)
        self.assertEqual(
            hashlib.sha256(persona_data.SYSTEM_PROMPT.encode()).hexdigest(),
            hashlib.sha256(sp.encode()).hexdigest(),
        )

    def test_compass_matches_main(self):
        _, models, default, _ = extract_main()
        from lexis.cortex.compass import DEFAULT_MODEL, MODELS, Compass

        self.assertEqual(MODELS, models)
        self.assertEqual(len(MODELS), 21)
        # The catalog still matches the original exactly. The default
        # deliberately no longer does: Master's decision (2026-11-10)
        # sets deepseek-v4.1-flash-1017-fast as the default and the
        # mandatory test model. The original main.py keeps its own
        # default (default, read live above) and is never modified.
        self.assertEqual(DEFAULT_MODEL, "deepseek-v4.1-flash-1017-fast")
        self.assertIn(default, MODELS)
        c = Compass()
        self.assertTrue(c.select("3"))
        self.assertEqual(c.current, models[2])
        self.assertTrue(c.select(models[0]))
        self.assertFalse(c.select("model-yang-tidak-ada"))
        self.assertFalse(c.select("99"))


class TestThinkFilter(unittest.TestCase):
    def test_cases(self):
        from lexis.cortex.pulse import ThinkFilter

        tf = ThinkFilter()
        self.assertEqual(tf.feed("halo "), "halo ")
        self.assertEqual(tf.feed("<thinking>zzz</thinking> dunia"), " dunia")
        tf2 = ThinkFilter()
        self.assertEqual(tf2.feed("abc<thinking>x</thinking>def"), "def")
        tf3 = ThinkFilter()
        self.assertEqual(tf3.feed("<thinking>belum selesai"), "")
        self.assertEqual(tf3.feed(" lanjut</thinking>ok"), "ok")


class TestForgeWarden(unittest.TestCase):
    def test_forge(self):
        from lexis.cortex import forge as fm
        from lexis.cortex.forge import Forge

        f = Forge()
        self.assertEqual(
            [s["name"] for s in f.schemas()],
            ["read_file", "write_file", "edit_file", "search_text",
             "list_dir", "run_command", "run_tests", "fetch_url",
             "browse_page"],
        )
        self.assertTrue(all("parameters" in s for s in f.schemas()))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "a.txt")
            f.call("write_file", path=p, content="isi")
            self.assertEqual(f.call("read_file", path=p), "isi")
        self.assertEqual(
            fm.find_read_marker("x [READ_FILE: C:\\a.txt ] y"), "C:\\a.txt"
        )
        self.assertEqual(
            fm.find_write_marker("t [WRITE_FILE: b.txt] halo [/WRITE_FILE]"),
            ("b.txt", "halo"),
        )
        self.assertIsNone(fm.find_read_marker("tidak ada"))

    def test_warden(self):
        from lexis.cortex.warden import ALLOW, ASK, WARN, Warden

        self.assertEqual(Warden("EMBER").decide("write"), ASK)
        self.assertEqual(Warden("EMBER").decide("read"), ALLOW)
        blaze = Warden("BLAZE")
        self.assertEqual(blaze.decide("write"), WARN)
        blaze.note_warned("write")
        self.assertEqual(blaze.decide("write"), ALLOW)
        self.assertEqual(Warden("INFERNO").decide("write"), ALLOW)
        self.assertEqual(Warden("sembarang").mode, "EMBER")


class TestLedgerVault(unittest.TestCase):
    def test_ledger_and_vault(self):
        from lexis.cortex.ledger import Ledger
        from lexis.cortex.vault import Vault

        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "state.db"))
            sid = led.start_session("m")
            led.append_message(sid, "user", "halo")
            self.assertEqual(
                led.load_messages(sid), [{"role": "user", "content": "halo"}]
            )
            self.assertEqual(led.last_session_id(), sid)
            led.register_config_doc("X.md", "abc", 3)
            self.assertEqual(led.config_docs()[0][0], "X.md")
            led.close()
            v = Vault()
            msgs = v.bootstrap()
            self.assertEqual(msgs[0]["role"], "system")
            self.assertEqual(len(msgs), 3)


class TestDocuments(unittest.TestCase):
    def test_document_versions(self):
        import hashlib

        from lexis.cortex.ledger import Ledger

        def sha(s):
            return hashlib.sha256(s.encode()).hexdigest()

        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "state.db"))
            self.assertEqual(led.store_document("A.md", "satu", sha("satu")), 1)
            # identical content: no new version
            self.assertEqual(led.store_document("A.md", "satu", sha("satu")), 1)
            # changed content: version 2, version 1 still intact in history
            self.assertEqual(led.store_document("A.md", "dua", sha("dua")), 2)
            latest = led.latest_document("A.md")
            self.assertEqual(latest["version"], 2)
            self.assertEqual(latest["content"], "dua")
            rows = led._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE name = 'A.md'"
            ).fetchone()[0]
            self.assertEqual(rows, 2)
            self.assertEqual(led.document_names(), ["A.md"])
            self.assertIsNone(led.latest_document("tidak-ada.md"))
            led.close()


class TestFindHome(unittest.TestCase):
    def setUp(self):
        import shutil

        from lexis.cortex import bridge

        self.bridge = bridge
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old_cwd = os.getcwd()
        self.addCleanup(os.chdir, self.old_cwd)
        self.old_override = os.environ.pop("LEXIS_HOME", None)
        self.addCleanup(self._restore_override)

    def _restore_override(self):
        if self.old_override is not None:
            os.environ["LEXIS_HOME"] = self.old_override

    def test_override_wins(self):
        os.environ["LEXIS_HOME"] = self.tmp
        self.assertEqual(self.bridge.find_home(), self.tmp)

    def test_cwd_with_config_wins(self):
        os.makedirs(os.path.join(self.tmp, "config"))
        os.chdir(self.tmp)
        self.assertEqual(self.bridge.find_home(), self.tmp)

    def test_source_tree_fallback(self):
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        os.chdir(bare)
        tree = os.path.join(self.tmp, "tree")
        fake_file = os.path.join(tree, "lexis", "cortex", "bridge.py")
        os.makedirs(os.path.dirname(fake_file))
        os.makedirs(os.path.join(tree, "config"))
        self.assertEqual(self.bridge.find_home(fake_file), tree)

    def test_plain_cwd_fallback(self):
        bare = os.path.join(self.tmp, "bare2")
        os.makedirs(bare)
        os.chdir(bare)
        tree = os.path.join(self.tmp, "installed")
        fake_file = os.path.join(tree, "lexis", "cortex", "bridge.py")
        os.makedirs(os.path.dirname(fake_file))
        self.assertEqual(self.bridge.find_home(fake_file), bare)


class TestPulseFakeStream(unittest.TestCase):
    def test_turns(self):
        from lexis.cortex import bridge
        from lexis.cortex.compass import Compass
        from lexis.cortex.forge import Forge
        from lexis.cortex.ledger import Ledger
        from lexis.cortex.pulse import Pulse
        from lexis.cortex.vault import Vault
        from lexis.cortex.warden import Warden

        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "state.db"))

            def build(script, ask_answer="y"):
                if script and isinstance(script[0], str):
                    script = [script]
                calls = {"n": 0}

                def fake_stream(model, messages, key):
                    idx = min(calls["n"], len(script) - 1)
                    calls["n"] += 1
                    return iter(script[idx])

                comp = Compass()
                vault = Vault()
                vault.bootstrap()
                sid = led.start_session(comp.current)
                tokens = []
                pulse = Pulse(
                    d, comp, vault, Forge(), Warden("EMBER"), led, sid,
                    workdir=d,
                    emit_token=tokens.append, emit_line=lambda t: None,
                    ask=lambda prompt: ask_answer,
                )
                orig = bridge.stream_chat
                bridge.stream_chat = fake_stream
                try:
                    result = pulse.handle_turn("halo")
                finally:
                    bridge.stream_chat = orig
                return result, vault, tokens

            result, vault, tokens = build(["halo ", "dunia"])
            self.assertEqual(result, "done")
            self.assertEqual("".join(tokens), "halo dunia")
            self.assertEqual(
                vault.messages()[-1],
                {"role": "assistant", "content": "halo dunia"},
            )

            target = os.path.join(d, "doc.txt")
            Path(target).write_text("ISI DOKUMEN", encoding="utf-8")
            result, vault, _ = build([
                [f"baik [READ_FILE: {target}]"],
                ["isi dokumen sudah kubaca"],
            ])
            # The original continues inside the same turn after a
            # read: the file content is injected and the model answers
            # again; the read-request reply itself is never stored.
            self.assertEqual(result, "done")
            self.assertTrue(
                any("HASIL BACA FILE" in m["content"] for m in vault.messages())
            )
            self.assertEqual(
                vault.messages()[-1],
                {"role": "assistant", "content": "isi dokumen sudah kubaca"},
            )

            out_file = os.path.join(d, "out.txt")
            result, _, _ = build([
                [f"[WRITE_FILE: {out_file}] konten baru [/WRITE_FILE]"],
                ["selesai"],
            ])
            self.assertEqual(result, "done")
            self.assertEqual(
                Path(out_file).read_text(encoding="utf-8"), "konten baru"
            )
            build(
                [f"[WRITE_FILE: {out_file}] jahat [/WRITE_FILE]"],
                ask_answer="n",
            )
            self.assertEqual(
                Path(out_file).read_text(encoding="utf-8"), "konten baru"
            )
            led.close()


class TestBridgeProviders(unittest.TestCase):
    """Providers (Master, 2026-11-10): unlimited, any endpoint,
    keys only ever in the profile .env."""

    def test_unlimited_providers_and_key_hygiene(self):
        from lexis.cortex import bridge

        with tempfile.TemporaryDirectory() as d:
            env_path = os.path.join(d, ".env")
            Path(env_path).write_text(
                "DEEPSEEK_API_KEY=legacy-fixture\n", encoding="utf-8"
            )
            self.assertEqual(bridge.provider_name(d), "Osvyn")
            self.assertEqual(bridge.current_key(d), "legacy-fixture")
            bridge.add_provider(
                d, "Kedua", "https://api.example.com/v1",
                "fixture-key-2",
            )
            self.assertEqual(bridge.provider_name(d), "Kedua")
            self.assertEqual(bridge.current_key(d), "fixture-key-2")
            self.assertEqual(
                bridge.base_url(d), "https://api.example.com/v1"
            )
            names = [p["name"] for p in bridge.list_providers(d)]
            self.assertEqual(names, ["Osvyn", "Kedua"])
            providers_text = Path(
                os.path.join(d, "providers.json")
            ).read_text(encoding="utf-8")
            self.assertNotIn("fixture-key-2", providers_text)
            self.assertIn(
                "LEXIS_PROVIDER_KEDUA_KEY=fixture-key-2",
                Path(env_path).read_text(encoding="utf-8"),
            )
            self.assertTrue(bridge.set_active_provider(d, "Osvyn"))
            self.assertEqual(bridge.current_key(d), "legacy-fixture")
            self.assertFalse(bridge.set_active_provider(d, "TidakAda"))


if __name__ == "__main__":
    unittest.main()
