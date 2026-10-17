from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import unittest

from microtools_free.cli import main
from microtools_free.demo import build_demo
from workspace import temp_workspace


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = temp_workspace()
        self.root = Path(self.temp.__enter__())
        self.addCleanup(self.temp.__exit__, None, None, None)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_promptdiff_text_and_difference_exit_codes(self):
        code, stdout, _ = self.invoke("promptdiff", EXAMPLES / "prompt-before.txt", EXAMPLES / "prompt-after.txt", "--format", "text")
        self.assertEqual(code, 1)
        self.assertIn("+State uncertainty", stdout)
        self.assertEqual(self.invoke("promptdiff", EXAMPLES / "prompt-before.txt", EXAMPLES / "prompt-before.txt")[0], 0)

    def test_configdiff_ignored_timestamp_has_two_changes(self):
        code, stdout, _ = self.invoke("configdiff", EXAMPLES / "config-before.json", EXAMPLES / "config-after.json", "--ignore", "/metadata/updated")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(stdout)["changes"]), 2)

    def test_doctor_valid_and_broken_exit_codes(self):
        self.assertEqual(self.invoke("jsonldoctor", EXAMPLES / "jobs-valid.jsonl", "--require", "id", "--require", "prompt")[0], 0)
        code, stdout, _ = self.invoke("jsonldoctor", EXAMPLES / "jobs-broken.jsonl", "--require", "prompt")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["rejected_rows"], 4)

    def test_doctor_copy_requires_explicit_permission_to_drop_rows(self):
        output = self.root / "copy.jsonl"
        source = EXAMPLES / "jobs-broken.jsonl"
        original = source.read_bytes()
        code, _, stderr = self.invoke("jsonldoctor", source, "--require", "prompt", "--write-valid", output)
        self.assertEqual(code, 2)
        self.assertIn("--drop-invalid", stderr)
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_doctor_filtered_copy_contains_only_accepted_original_rows(self):
        output = self.root / "copy.jsonl"
        code, stdout, _ = self.invoke("jsonldoctor", EXAMPLES / "jobs-broken.jsonl", "--require", "prompt", "--write-valid", output, "--drop-invalid")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["filtered_copy"]["rows_written"], 2)
        self.assertEqual([json.loads(line)["id"] for line in output.read_text().splitlines()], ["greeting", "summary"])

    def test_valid_copy_adds_final_newline_and_removes_bom(self):
        source, output = self.root / "input.jsonl", self.root / "copy.jsonl"
        source.write_bytes(b'\xef\xbb\xbf{"id":"a"}')
        code, stdout, _ = self.invoke("jsonldoctor", source, "--write-valid", output)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["utf8_bom_accepted"])
        self.assertEqual(output.read_bytes(), b'{"id":"a"}\n')

    def test_existing_filtered_copy_prevents_report_creation(self):
        output, report = self.root / "copy.jsonl", self.root / "report.json"
        output.write_text("original", encoding="utf-8")
        code, _, _ = self.invoke("jsonldoctor", EXAMPLES / "jobs-valid.jsonl", "--write-valid", output, "--output", report)
        self.assertEqual(code, 2)
        self.assertEqual(output.read_text(), "original")
        self.assertFalse(report.exists())

    def test_output_paths_must_differ(self):
        output = self.root / "output.json"
        self.assertEqual(self.invoke("logredact", EXAMPLES / "demo.log", "--output", output, "--report", output)[0], 2)
        self.assertFalse(output.exists())

    def test_log_default_summary_does_not_print_values(self):
        code, stdout, _ = self.invoke("logredact", EXAMPLES / "demo.log")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["redactions"], 4)
        self.assertNotIn("DEMO_API_KEY_NOT_REAL", stdout)
        self.assertNotIn("DEMO_LITERAL_NOT_REAL", stdout)

    def test_log_preview_and_separate_output_preserve_original(self):
        source, output, report = EXAMPLES / "demo.log", self.root / "redacted.log", self.root / "summary.json"
        original = source.read_bytes()
        code, stdout, _ = self.invoke("logredact", source, "--secrets-file", EXAMPLES / "demo-secrets.txt", "--emails", "--preview", "--output", output, "--report", report)
        self.assertEqual(code, 0)
        self.assertNotIn("DEMO_LITERAL_NOT_REAL", stdout)
        self.assertNotIn("user@example.test", stdout)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(json.loads(report.read_text())["redactions"], 6)

    def test_existing_log_output_prevents_writes(self):
        output, report = self.root / "redacted.log", self.root / "summary.json"
        output.write_text("original", encoding="utf-8")
        code, _, _ = self.invoke("logredact", EXAMPLES / "demo.log", "--output", output, "--report", report)
        self.assertEqual(code, 2)
        self.assertEqual(output.read_text(), "original")
        self.assertFalse(report.exists())

    def test_missing_file_gives_no_traceback(self):
        code, _, stderr = self.invoke("logredact", self.root / "missing.log")
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("Error:"))
        self.assertNotIn("Traceback", stderr)

    def test_empty_secret_line_ignored_but_short_literal_is_rejected(self):
        path = self.root / "secrets.txt"
        path.write_text("\nabc\n", encoding="utf-8")
        self.assertEqual(self.invoke("logredact", EXAMPLES / "demo.log", "--secrets-file", path)[0], 2)

    def test_complete_demo_checks_and_file_outputs(self):
        report = build_demo(self.root / "demo")
        self.assertTrue(report["all_demo_checks_passed"])
        self.assertTrue((self.root / "demo" / "redacted-demo.log").exists())
