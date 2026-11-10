# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""Fase 3 Cortex verification: memory tiers and fact extraction,
prism compaction under the anti-forgetting doctrine, compass
routing and fallback from probe data, the judge's external-signal
verdicts, plan mode with its tool-level write ban, the golden task
set end to end, and the Visor's ladder, plan flow, and check line.
Run from the project root:  python -m unittest tests.test_fase3 -v
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexis.cortex import bridge  # noqa: E402
from lexis.cortex import judge as judge_mod  # noqa: E402
from lexis.cortex import prism  # noqa: E402
from lexis.cortex.compass import Compass  # noqa: E402
from lexis.cortex.forge import Forge  # noqa: E402
from lexis.cortex.ledger import Ledger  # noqa: E402
from lexis.cortex.pulse import Pulse, parse_plan  # noqa: E402
from lexis.cortex.vault import Vault, extract_facts  # noqa: E402
from lexis.cortex.warden import DENY, Warden  # noqa: E402


def make_pulse(root, stream, mode="INFERNO", events=None):
    ledger = Ledger(os.path.join(root, "state.db"))
    vault = Vault()
    sid = ledger.start_session("test-model")
    for m in vault.bootstrap():
        ledger.append_message(sid, m["role"], m["content"])
    compass = Compass()
    pulse = Pulse(
        root, compass, vault, Forge(), Warden(mode), ledger, sid,
        workdir=root,
        emit_token=lambda t: None,
        emit_line=lambda t: None,
        ask=lambda prompt: "y",
        on_event=(lambda k, d: events.append((k, d)))
        if events is not None else None,
    )
    old = bridge.stream_chat
    bridge.stream_chat = stream
    return pulse, ledger, vault, old


class TestFactsAndTiers(unittest.TestCase):
    def test_extract_classifies(self):
        found = dict(
            (text, kind) for kind, text in extract_facts(
                "I decided to ship every Friday. "
                "My name is Riki and I prefer short answers. "
                "I will send the files tomorrow morning. "
                "The weather is fine today."
            )
        )
        self.assertIn("decision", found.values())
        self.assertIn("fact", found.values())
        self.assertIn("promise", found.values())
        self.assertNotIn(
            "The weather is fine today.", list(found.keys())
        )

    def test_learn_dedupes_and_counts(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            ledger = Ledger(os.path.join(tmp, "state.db"))
            self.addCleanup(ledger.close)
            sid = ledger.start_session("m")
            vault = Vault()
            n1 = vault.learn_from(ledger, sid, "I prefer dark themes.")
            n2 = vault.learn_from(ledger, sid, "I prefer dark themes.")
            self.assertEqual((n1, n2), (1, 0))
            self.assertEqual(ledger.fact_count(session_id=sid), 1)
            self.assertEqual(vault.recall(ledger)[0]["kind"], "fact")

    def test_episode_tags_and_cost_rows(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            ledger = Ledger(os.path.join(tmp, "state.db"))
            self.addCleanup(ledger.close)
            sid = ledger.start_session("m")
            ledger.tag_session(sid, "lexis")
            self.assertEqual(ledger.sessions()[0]["tags"], ["lexis"])
            ledger.record_cost(sid, "m", 1.5, 100, 50, "done")
            rows = ledger.cost_rows()
            self.assertEqual(rows[0]["prompt_tokens_est"], 100)
            summary = Compass.cost_summary(ledger)
            self.assertEqual(summary["m"]["done_rate"], 1.0)
            self.assertEqual(summary["m"]["avg_tokens"], 150)


class TestPrism(unittest.TestCase):
    def test_compaction_preserves_anchors_and_facts(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            ledger = Ledger(os.path.join(tmp, "state.db"))
            self.addCleanup(ledger.close)
            vault = Vault()
            sid = ledger.start_session("m")
            anchors = vault.bootstrap()
            filler = "x" * 60_000
            vault.add("user", "I decided to ship every Friday. " + filler)
            for i in range(8):
                vault.add("user" if i % 2 == 0 else "assistant",
                          f"message {i} " + filler)
            vault.add("assistant", "recent one")
            vault.add("user", "recent two")
            self.assertTrue(prism.needs_compaction(vault.messages()))
            report = prism.compact(vault, ledger, sid, keep_last=2)
            self.assertIsNotNone(report)
            msgs = vault.messages()
            self.assertEqual(msgs[:3], anchors)
            self.assertIn("condensed by Lexis", msgs[3]["content"])
            self.assertEqual(msgs[-1]["content"], "recent two")
            self.assertGreaterEqual(report["facts"], 1)
            self.assertLess(report["after_tokens"], report["before_tokens"])
            kinds = [f["kind"] for f in ledger.facts()]
            self.assertIn("decision", kinds)

    def test_compaction_none_when_small(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            ledger = Ledger(os.path.join(tmp, "state.db"))
            self.addCleanup(ledger.close)
            vault = Vault()
            sid = ledger.start_session("m")
            vault.bootstrap()
            self.assertIsNone(prism.compact(vault, ledger, sid))
            self.assertFalse(prism.needs_compaction(vault.messages()))


class TestCompassRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "probe_result.txt"), "w") as f:
            f.write("deepseek-v4-pro: OK -> fine\n")
            f.write("qwen3.7-plus: ERR Read timed out.\n")
            f.write("gemini-3-pro-image: OK -> image\n")
            f.write("muse-spark-1.3: HTTP 400 -> no\n")
        self.compass = Compass(root=self.tmp)

    def test_probe_and_chain(self):
        c = self.compass
        self.assertTrue(c.answered("deepseek-v4-pro"))
        self.assertFalse(c.answered("qwen3.7-plus"))
        self.assertFalse(c.answered("muse-spark-1.3"))
        chain = c.chain()
        self.assertEqual(chain[0], c.current)
        self.assertNotIn("qwen3.7-plus", chain)
        self.assertNotIn("gemini-3-pro-image", chain)
        self.assertLessEqual(len(chain), 4)
        self.assertEqual(c.backup_name(), chain[1])

    def test_route_auto(self):
        c = self.compass
        self.assertEqual(c.route("def f(): pass  # bug here"), c.current)
        c.auto = True
        self.assertEqual(c.route("def f(): pass  # bug here"),
                         "deepseek-v4-pro")
        self.assertEqual(c.route("x" * 700), "deepseek-v4-pro")
        self.assertEqual(c.route("hi"), "deepseek-v4.1-flash-1017-fast")
        self.assertTrue(c.select("auto"))
        self.assertFalse(c.select("not-a-model"))


class TestFallback(unittest.TestCase):
    def test_error_then_empty_then_success(self):
        events = []
        calls = []

        def fake(model, messages, key):
            calls.append(model)
            if len(calls) == 1:
                raise RuntimeError("boom")
            if len(calls) == 2:
                return
                yield  # empty stream
            yield "recovered reply"

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            pulse, ledger, vault, old = make_pulse(tmp, fake, events=events)
            self.addCleanup(ledger.close)
            try:
                outcome = pulse.handle_turn("hello there")
            finally:
                bridge.stream_chat = old
            self.assertEqual(outcome, "done")
            self.assertEqual(len(calls), 3)
            kinds = [k for k, _ in events]
            self.assertEqual(kinds.count("model_fallback"), 2)
            last = [m for m in vault.messages()
                    if m["role"] == "assistant"][-1]
            self.assertEqual(last["content"], "recovered reply")


class TestJudge(unittest.TestCase):
    def test_verdicts(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            v = judge_mod.verify_turn("", [], tmp)
            self.assertEqual(v.status, "fail")
            v = judge_mod.verify_turn("leftover [/WRITE_FILE] here", [], tmp)
            self.assertEqual(v.status, "fail")
            good = os.path.join(tmp, "a.py")
            v = judge_mod.verify_turn(
                "done",
                [{"name": "write_file", "ok": True, "path": good,
                  "content": "x = 1\n"}],
                tmp,
            )
            self.assertEqual(v.status, "fail")  # not on disk yet
            with open(good, "w") as f:
                f.write("x = 1\n")
            v = judge_mod.verify_turn(
                "done",
                [{"name": "write_file", "ok": True, "path": good,
                  "content": "x = 1\n"}],
                tmp,
            )
            self.assertEqual(v.status, "pass")
            bad = os.path.join(tmp, "b.py")
            with open(bad, "w") as f:
                f.write("def broken(:\n")
            v = judge_mod.verify_turn(
                "done",
                [{"name": "write_file", "ok": True, "path": bad,
                  "content": "def broken(:\n"}],
                tmp,
            )
            self.assertEqual(v.status, "fail")
            v = judge_mod.verify_turn(
                "done",
                [{"name": "read_file", "ok": False, "detail": "missing"}],
                tmp,
            )
            self.assertEqual(v.status, "warn")


class TestPlanMode(unittest.TestCase):
    def test_parse_plan(self):
        steps = parse_plan(
            "Here is the plan:\n1. Gather the files\n- Write the draft\n"
            "3) Send it over\n[WRITE_FILE: x.py]nope\n[/WRITE_FILE]",
            "goal",
        )
        self.assertEqual(
            steps, ["Gather the files", "Write the draft", "Send it over"]
        )
        self.assertEqual(parse_plan("no steps here at all", "goal"), ["goal"])

    def test_draft_holds_writes_and_run_executes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            held = os.path.join(tmp, "held.py")

            def fake(model, messages, key):
                last_user = [m for m in messages
                             if m["role"] == "user"][-1]["content"]
                if last_user.startswith("Plan this task"):
                    yield ("1. Write the hello file\n2. Read it back\n"
                           f"[WRITE_FILE: {held}]x = 1\n[/WRITE_FILE]")
                else:
                    yield "step done"

            pulse, ledger, vault, old = make_pulse(tmp, fake)
            self.addCleanup(ledger.close)
            try:
                self.assertEqual(
                    pulse.warden.decide("write"), "allow"  # INFERNO
                )
                pulse.warden.planning = True
                self.assertEqual(pulse.warden.decide("write"), DENY)
                pulse.warden.planning = False
                steps = pulse.draft_plan("make hello")
                self.assertEqual(
                    steps, ["Write the hello file", "Read it back"]
                )
                self.assertFalse(
                    os.path.exists(os.path.join(tmp, "held.py"))
                )
                self.assertEqual(pulse.run_plan(), "done")
                self.assertTrue(
                    all(s["state"] == "done" for s in pulse.plan)
                )
            finally:
                bridge.stream_chat = old


class TestCompletionLoop(unittest.TestCase):
    """The completion loop's write side (golden run 2 finding,
    2026-11-10): one reply may carry several write markers; all
    of them execute as a unit, and a repeated write of the same
    path with identical content is not executed again."""

    def test_multi_marker_reply_executes_as_one_unit(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        a = os.path.join(tmp, "a.py")
        b = os.path.join(tmp, "b.py")
        calls = []

        def fake(model, messages, key):
            calls.append(1)
            if len(calls) == 1:
                yield (f"[WRITE_FILE: {a}]print('a')\n[/WRITE_FILE]\n"
                       f"[WRITE_FILE: {b}]print('b')\n[/WRITE_FILE]")
            else:
                yield "both files written"

        pulse, ledger, vault, old = make_pulse(tmp, fake)
        self.addCleanup(ledger.close)
        try:
            self.assertEqual(pulse.handle_turn("write both"), "done")
        finally:
            bridge.stream_chat = old
        self.assertEqual(len(calls), 2)
        with open(a, encoding="utf-8") as f:
            self.assertEqual(f.read(), "print('a')")
        with open(b, encoding="utf-8") as f:
            self.assertEqual(f.read(), "print('b')")

    def test_duplicate_write_is_not_repeated(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        a = os.path.join(tmp, "a.py")
        calls = []

        def fake(model, messages, key):
            calls.append(1)
            yield f"[WRITE_FILE: {a}]print('a')\n[/WRITE_FILE]"

        pulse, ledger, vault, old = make_pulse(tmp, fake)
        self.addCleanup(ledger.close)
        try:
            self.assertEqual(pulse.handle_turn("write it"), "done")
        finally:
            bridge.stream_chat = old
        # Call 1 writes and continues; call 2 repeats the same
        # write, and the guard ends the turn instead of looping.
        self.assertEqual(len(calls), 2)
        with open(a, encoding="utf-8") as f:
            self.assertEqual(f.read(), "print('a')")


class TestGoldenSet(unittest.TestCase):
    def test_golden_tasks_end_to_end(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            good = os.path.join(tmp, "hello.py")
            bad = os.path.join(tmp, "broken.py")
            replies = iter([
                f"[WRITE_FILE: {good}]print('hello')\n[/WRITE_FILE]",
                "hello written",
                f"[WRITE_FILE: {bad}]def broken(:\n[/WRITE_FILE]",
                "broken written",
                f"[READ_FILE: {good}]",
                "isi file sudah kubaca",
            ])

            def fake(model, messages, key):
                yield next(replies)

            pulse, ledger, vault, old = make_pulse(tmp, fake)
            self.addCleanup(ledger.close)
            try:
                self.assertEqual(pulse.handle_turn("write hello"), "done")
                self.assertEqual(pulse.handle_turn("write broken"), "done")
                # A read continues inside the same turn (the original
                # looped with `continue`): the follow-up reply ends it.
                self.assertEqual(pulse.handle_turn("read it"), "done")
            finally:
                bridge.stream_chat = old
            self.assertTrue(os.path.isfile(good))
            verdicts = [
                d for (d,) in ledger._conn.execute(
                    "SELECT detail FROM events WHERE kind = 'judge' "
                    "ORDER BY id"
                ).fetchall()
            ]
            self.assertTrue(verdicts[0].startswith("pass"))
            # The broken write is the third judged call (each write
            # is followed by its continuation call).
            self.assertTrue(verdicts[2].startswith("fail"))
            # 6 model calls: write + continuation, write +
            # continuation, read + continuation.
            self.assertEqual(len(ledger.cost_rows()), 6)


# ---------------- Visor ----------------

from lexis.visor.app import BootScreen, LexisVisor  # noqa: E402
from lexis.visor.banner import banner_text  # noqa: E402


def chat_text(app) -> str:
    parts = []
    for w in app.query("#chat Static"):
        try:
            parts.append(str(w.render()))
        except Exception:
            pass
    return "\n".join(parts)


async def wait_for(predicate, timeout=12.0):
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(0.1)
        waited += 0.1
    return predicate()


class VisorFase3Test(unittest.IsolatedAsyncioTestCase):
    async def test_ladder_inferno_gate_and_mode_panel(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            app = LexisVisor(root=tmp)
            async with app.run_test(size=(130, 48)) as pilot:
                await pilot.pause()
                panel = str(app.query_one("#pnl-mode").render())
                self.assertIn("COMPLIANCE", panel)
                self.assertIn("INFERNO", panel)
                app.submit_text("/mode")
                await wait_for(
                    lambda: app.screen.__class__.__name__ == "LadderScreen"
                )
                await pilot.pause()
                from textual.widgets import OptionList

                lst = app.screen.query_one(OptionList)
                for i in range(lst.option_count):
                    if lst.get_option_at_index(i).id == "INFERNO":
                        lst.highlighted = i
                await pilot.press("enter")
                await wait_for(
                    lambda: app.screen.__class__.__name__ == "InfernoScreen"
                )
                await pilot.pause()
                stay = app.screen.query_one("#stay")
                stay.press()
                await pilot.pause()
                self.assertEqual(app.warden.mode, "EMBER")
                app.submit_text("/mode INFERNO")
                await wait_for(
                    lambda: app.screen.__class__.__name__ == "InfernoScreen"
                )
                await pilot.pause()
                enter = app.screen.query_one("#enter")
                enter.press()
                await wait_for(lambda: app.warden.mode == "INFERNO")
                self.assertIn("INFERNO", str(app.query_one("#hdr").render()))

    async def test_plan_flow_and_check_line(self):
        def fake(model, messages, key):
            last_user = [m for m in messages
                         if m["role"] == "user"][-1]["content"]
            if last_user.startswith("Plan this task"):
                yield "1. First small step\n2. Second small step"
            else:
                yield "all done here"

        old = bridge.stream_chat
        bridge.stream_chat = fake
        try:
            tmp = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, tmp, True)
            if True:
                app = LexisVisor(root=tmp)
                async with app.run_test(size=(130, 48)) as pilot:
                    await pilot.pause()
                    app.submit_text("/plan prepare the summary")
                    await wait_for(lambda: len(app.pulse.plan) == 2)
                    await wait_for(lambda: "Plan ready" in chat_text(app))
                    self.assertIn(
                        "Plan ready", chat_text(app)
                    )
                    app.submit_text("/plan run")
                    await wait_for(
                        lambda: all(
                            s["state"] == "done" for s in app.pulse.plan
                        )
                    )
                    await wait_for(
                        lambda: "Plan complete" in chat_text(app)
                    )
                    text = chat_text(app)
                    self.assertIn("Plan complete", text)
                    self.assertIn("Checked:", text)
        finally:
            bridge.stream_chat = old


class TestBootScreen(unittest.IsolatedAsyncioTestCase):
    async def test_boot_reveals_real_stages_and_hands_over(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            app = LexisVisor(root=tmp)
            async with app.run_test(size=(130, 48)) as pilot:
                await pilot.pause()
                stages = app._boot_stages()
                self.assertTrue(
                    any("Configuration" in s for s in stages)
                )
                self.assertTrue(
                    any("documents loaded" in s for s in stages)
                )
                self.assertTrue(
                    any("Compliance" in s for s in stages)
                )
                app.push_screen(
                    BootScreen(banner_text(), stages, interval=0.01)
                )
                ok = await wait_for(
                    lambda: app.screen.__class__.__name__ != "BootScreen"
                )
                self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
