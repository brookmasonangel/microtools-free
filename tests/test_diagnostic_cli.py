from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import unittest

from microtools_free.cli import main
from workspace import temp_workspace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class DiagnosticCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = temp_workspace()
        self.root = Path(self.temp.__enter__())
        self.addCleanup(self.temp.__exit__, None, None, None)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(arg) for arg in args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_complete_stream_passes_and_saved_field_loss_returns_one(self):
        self.assertEqual(self.invoke("streamusageaudit", EXAMPLES / "stream-complete.sse")[0], 0)
        code, out, err = self.invoke("streamusageaudit", EXAMPLES / "stream-complete.sse",
                                     "--saved", EXAMPLES / "stream-saved.json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["comparison"]["status"], "different")
        self.assertEqual(err, "")

    def test_saved_usage_flag_requires_file(self):
        code, _, err = self.invoke("streamusageaudit", EXAMPLES / "stream-complete.sse", "--saved-is-usage")
        self.assertEqual(code, 2)
        self.assertIn("--saved", err)

    def test_retry_finding_and_invalid_window_exit_codes(self):
        code, out, _ = self.invoke("retrylens", EXAMPLES / "retry-attempts.jsonl")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["follow_ups_before_hint"], 1)
        for window in ["0", "nan", "inf", "3601"]:
            with self.subTest(window=window):
                self.assertEqual(self.invoke("retrylens", EXAMPLES / "retry-attempts.jsonl", "--burst-window", window)[0], 2)

    def test_batch_kind_and_endpoint_flags(self):
        self.assertEqual(self.invoke("batchcontractcheck", EXAMPLES / "batch-input.jsonl",
                                    "--endpoint", "/v1/chat/completions")[0], 0)
        self.assertEqual(self.invoke("batchcontractcheck", EXAMPLES / "batch-results.jsonl",
                                    "--kind", "result")[0], 0)
        self.assertEqual(self.invoke("batchcontractcheck", EXAMPLES / "batch-results.jsonl",
                                    "--kind", "error")[0], 1)
        self.assertEqual(self.invoke("batchcontractcheck", EXAMPLES / "batch-results.jsonl",
                                    "--kind", "result", "--endpoint", "/v1/responses")[0], 2)

    def test_each_new_command_creates_report_and_preserves_input(self):
        for command, name in [("streamusageaudit", "stream-complete.sse"),
                              ("retrylens", "retry-attempts.jsonl"), ("batchcontractcheck", "batch-input.jsonl")]:
            with self.subTest(command=command):
                source = EXAMPLES / name
                original = source.read_bytes()
                output = self.root / (command + ".json")
                code, out, err = self.invoke(command, source, "--output", output)
                self.assertIn(code, [0, 1])
                self.assertIn("Created report", out)
                self.assertIn("tool", json.loads(output.read_text()))
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(err, "")

    def test_existing_outputs_and_input_as_output_are_refused(self):
        for command, name in [("streamusageaudit", "stream-complete.sse"),
                              ("retrylens", "retry-attempts.jsonl"), ("batchcontractcheck", "batch-input.jsonl")]:
            with self.subTest(command=command):
                output = self.root / (command + ".json")
                output.write_text("existing", encoding="utf-8")
                self.assertEqual(self.invoke(command, EXAMPLES / name, "--output", output)[0], 2)
                self.assertEqual(output.read_text(), "existing")
                source = EXAMPLES / name
                original = source.read_bytes()
                self.assertEqual(self.invoke(command, source, "--output", source)[0], 2)
                self.assertEqual(source.read_bytes(), original)

    def test_invalid_json_is_a_diagnostic_and_bad_encoding_is_operational_error(self):
        source = self.root / "broken"
        source.write_text('{"private-duplicate":1,"private-duplicate":2}\n', encoding="utf-8")
        code, out, err = self.invoke("batchcontractcheck", source)
        self.assertEqual(code, 1)
        self.assertNotIn("private-duplicate", out + err)
        source.write_bytes(b"\xff")
        for command in ["streamusageaudit", "retrylens", "batchcontractcheck"]:
            with self.subTest(command=command):
                code, _, err = self.invoke(command, source)
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", err)

    def test_missing_files_and_invalid_issue_limits_do_not_create_reports(self):
        for command, name in [("streamusageaudit", "stream-complete.sse"),
                              ("retrylens", "retry-attempts.jsonl"), ("batchcontractcheck", "batch-input.jsonl")]:
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command, self.root / "missing")[0], 2)
                output = self.root / (command + ".json")
                self.assertEqual(self.invoke(command, EXAMPLES / name, "--max-issues", "0", "--output", output)[0], 2)
                self.assertFalse(output.exists())
