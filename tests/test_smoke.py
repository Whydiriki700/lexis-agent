"""Smoke tests for the packaging foundation (stdlib unittest, no extras)."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import lexis
from lexis import cli, doctor


class VersionTest(unittest.TestCase):
    def test_version_is_semver_shaped(self):
        parts = lexis.__version__.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_cli_no_args_exits_zero_and_names_itself(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main([])
        self.assertEqual(code, 0)
        self.assertIn("Lexis Agent", out.getvalue())


class EntryRoutingTest(unittest.TestCase):
    """Master's entry decision (2026-11-10): bare `lexis` in a
    terminal opens the Visor; the plain loop is `lexis chat`."""

    def test_no_args_on_a_terminal_opens_the_visor(self):
        class TtyOut(io.StringIO):
            def isatty(self):
                return True

        calls = []

        def fake_visor(argv=None):
            calls.append(list(argv or []))
            return 0

        with mock.patch("lexis.visor.app.run_visor", fake_visor):
            with redirect_stdout(TtyOut()):
                code = cli.main([])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [[]])

    def test_chat_subcommand_opens_plain_chat(self):
        with mock.patch.object(cli, "run_chat", return_value=7) as chat:
            code = cli.main(["chat"])
        self.assertEqual(code, 7)
        chat.assert_called_once_with([])


class DoctorTest(unittest.TestCase):
    def test_doctor_reports_and_returns_an_exit_code(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = doctor.run()
        self.assertIn(code, (0, 1))
        text = out.getvalue()
        self.assertIn("Lexis doctor", text)
        self.assertIn("Python", text)
        self.assertIn("Configuration folder", text)


if __name__ == "__main__":
    unittest.main()
