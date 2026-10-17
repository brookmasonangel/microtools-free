from __future__ import annotations

import unittest
from pathlib import Path

from microtools_free.common import ToolError, parse_json, read_text, write_new
from microtools_free.diffing import config_diff, prompt_diff
from microtools_free.jsonldoctor import audit, filtered_text
from workspace import temp_workspace


class FileTests(unittest.TestCase):
    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        for text in ['{"a":1,"a":2}', 'NaN', '1e400', '9' * 5000]:
            with self.subTest(text=text[:25]), self.assertRaises(ToolError):
                parse_json(text)

    def test_bom_option_and_newline_preservation(self):
        with temp_workspace() as temp:
            path = Path(temp) / "file.txt"
            path.write_bytes(b"\xef\xbb\xbfhello\r\nworld")
            self.assertEqual(read_text(path), "hello\r\nworld")
            self.assertTrue(read_text(path, preserve_bom=True).startswith("\ufeff"))

    def test_invalid_utf8_is_an_actionable_error(self):
        with temp_workspace() as temp:
            path = Path(temp) / "bad.txt"
            path.write_bytes(b"\xff")
            with self.assertRaises(ToolError):
                read_text(path)

    def test_existing_output_is_preserved(self):
        with temp_workspace() as temp:
            path = Path(temp) / "report.json"
            write_new(path, "original")
            with self.assertRaises(ToolError):
                write_new(path, "replacement")
            self.assertEqual(path.read_text(), "original")


class DiffTests(unittest.TestCase):
    def test_prompt_change_and_final_newline_are_reported(self):
        report = prompt_diff("hello\n", "hello")
        self.assertTrue(report["changed"])
        self.assertIn("No newline at end of file", report["diff"])
        self.assertNotEqual(report["before_text_sha256"], report["after_text_sha256"])

    def test_whitespace_mode_is_explicit(self):
        self.assertTrue(prompt_diff("hello  world\n", "hello world")["changed"])
        self.assertFalse(prompt_diff("hello  world\n", "hello world", ignore_whitespace=True)["changed"])

    def test_unicode_prompt_and_identical_text(self):
        self.assertFalse(prompt_diff("你好\n", "你好\n")["changed"])
        self.assertIn("+café", prompt_diff("tea\n", "café\n")["diff"])

    def test_json_key_order_and_numeric_equivalence(self):
        self.assertFalse(config_diff({"a": 1, "b": 2}, {"b": 2.0, "a": 1.0})["changed"])

    def test_boolean_is_distinct_from_number(self):
        self.assertTrue(config_diff({"enabled": True}, {"enabled": 1})["changed"])

    def test_array_order_and_escaped_paths(self):
        report = config_diff({"a/b~c": [1, 2]}, {"a/b~c": [2, 1, 3]})
        self.assertEqual([r["path"] for r in report["changes"]], ["/a~1b~0c/0", "/a~1b~0c/1", "/a~1b~0c/2"])

    def test_ignore_subtree_and_root(self):
        self.assertFalse(config_diff({"meta": {"time": 1}}, {"meta": {"time": 2}}, ignore=["/meta"])["changed"])
        self.assertFalse(config_diff(1, 2, ignore=[""])["changed"])

    def test_invalid_pointer_is_rejected(self):
        for paths in [["meta"], ["/meta~2"], [["bad"]]]:
            with self.subTest(paths=paths), self.assertRaises(ToolError):
                config_diff({}, {}, ignore=paths)


class DoctorTests(unittest.TestCase):
    def test_valid_file_and_exact_row_text_are_retained(self):
        source = '{ "id": "a", "value": 1.000 }\r\n{"id":"b"}\r\n'
        report, rows = audit(source)
        self.assertTrue(report["valid"])
        self.assertEqual(report["accepted_rows"], 2)
        self.assertEqual(filtered_text(rows), '{ "id": "a", "value": 1.000 }\n{"id":"b"}\n')

    def test_reports_all_bad_rows_and_original_line_numbers(self):
        text = '{"id":"a","prompt":"x"}\n{"id":"a","prompt":"y"}\n{"id":"b"}\n{"id":\n\n'
        report, accepted = audit(text, required_fields=["id", "prompt"])
        self.assertEqual(report["accepted_rows"], 1)
        self.assertEqual(report["rejected_rows"], 4)
        self.assertEqual([issue["line"] for issue in report["issues"]], [2, 3, 4, 5])
        self.assertEqual(report["issues"][0]["first_line"], 1)

    def test_unicode_line_separators_inside_strings_are_not_new_records(self):
        text = '{"id":"a","text":"a\u0085b\u2028c"}\n{"id":"b"}\n'
        report, _ = audit(text)
        self.assertTrue(report["valid"])
        self.assertEqual(report["physical_lines"], 2)

    def test_duplicate_json_keys_and_invalid_unicode_are_rejected(self):
        for text in ['{"id":"a","id":"b"}\n', '{"text":"\\ud800"}\n', '{"value":NaN}\n']:
            with self.subTest(text=text):
                report, _ = audit(text)
                self.assertEqual(report["issues"][0]["code"], "invalid_json")

    def test_bom_accepted_and_missing_final_newline_not_an_error(self):
        report, _ = audit('\ufeff{"id":"a"}')
        self.assertTrue(report["valid"])
        self.assertTrue(report["utf8_bom_accepted"])
        self.assertFalse(report["trailing_newline"])

    def test_empty_input_and_blank_lines_fail(self):
        for text in ["", "\ufeff", "\n"]:
            with self.subTest(text=text):
                report, _ = audit(text)
                self.assertFalse(report["valid"])

    def test_top_level_objects_only(self):
        report, rows = audit('[]\nnull\n42\n"hello"\n')
        self.assertFalse(report["valid"])
        self.assertEqual(report["rejected_rows"], 4)
        self.assertEqual(rows, [])

    def test_id_optional_unless_required_but_present_ids_must_be_strings(self):
        self.assertTrue(audit('{"prompt":"x"}\n')[0]["valid"])
        self.assertFalse(audit('{"prompt":"x"}\n', required_fields=["id"])[0]["valid"])
        for value in ['1', 'null', 'true', '""']:
            self.assertFalse(audit('{"id":' + value + '}\n')[0]["valid"])

    def test_custom_id_name_and_disabled_id_checks(self):
        text = '{"record":"a","id":1}\n{"record":"a","id":1}\n'
        report, _ = audit(text, id_field="record")
        self.assertEqual(report["issues"][0]["code"], "duplicate_id")
        self.assertTrue(audit(text, id_field=None)[0]["valid"])

    def test_issue_details_truncated_without_hiding_total_errors(self):
        report, _ = audit('broken\nbroken\nbroken\n', max_issues=2)
        self.assertEqual(report["total_issues"], 3)
        self.assertEqual(len(report["issues"]), 2)
        self.assertTrue(report["issue_details_truncated"])
        self.assertFalse(report["valid"])

    def test_no_id_or_row_value_dump_in_audit_report(self):
        import json
        text = '{"id":"PRIVATE_EXAMPLE_ID","value":"PRIVATE_EXAMPLE_CONTENT"}\n{"id":"PRIVATE_EXAMPLE_ID"}\n'
        report, _ = audit(text)
        self.assertNotIn("PRIVATE_EXAMPLE_ID", json.dumps(report))
        self.assertNotIn("PRIVATE_EXAMPLE_CONTENT", json.dumps(report))

    def test_bad_parameters_are_errors(self):
        for kwargs in [{"max_issues": 0}, {"id_field": ""}, {"required_fields": [""]}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolError):
                audit('{}\n', **kwargs)
