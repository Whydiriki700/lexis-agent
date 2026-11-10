"""Smoke tests for the packaging foundation (stdlib unittest, no extras)."""

import io
import unittest
from contextlib import redirect_stdout

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
