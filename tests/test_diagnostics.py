from __future__ import annotations

import json
import unittest

from microtools_free.batchcontract import audit_batch, endpoints, record_issues, schema
from microtools_free.common import ToolError
from microtools_free.diagnostics import MAX_RECORDS
from microtools_free.retrylens import audit_retries
from microtools_free.streamusage import audit_stream


def counts(prompt=12, completion=3, **extra):
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion, **extra}


def chunk(usage=None, *, finished=True, identifier="fictional-stream"):
    return {"id": identifier, "object": "chat.completion.chunk", "usage": usage,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if finished else None}]}


def sse(*values, done=True):
    events = ["data: " + json.dumps(x, ensure_ascii=False) + "\n\n" for x in values]
    return "".join(events) + ("data: [DONE]\n\n" if done else "")


def jsonl(*rows):
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)


def attempt(number=1, *, operation="fictional-operation", start=0, response=1, headers=None):
    return {"operation_id": operation, "attempt": number,
            "started_at": f"2026-10-17T00:00:{start:02d}Z",
            "response_at": f"2026-10-17T00:00:{response:02d}Z",
            "status_code": 429 if number == 1 else 200,
            "response_headers": headers or {}}


def batch_input(identifier="fictional-row", *, url="/v1/chat/completions", model="example-model"):
    return {"custom_id": identifier, "method": "POST", "url": url, "body": {"model": model}}


def batch_result(status=200, *, identifier="fictional-row"):
    return {"id": "fictional-result", "custom_id": identifier,
            "response": {"status_code": status, "request_id": None, "body": {}}, "error": None}


class StreamUsageTests(unittest.TestCase):
    def test_complete_capture_matches_saved_response(self):
        report = audit_stream(sse(chunk(counts())), saved={"usage": counts()}, compare_saved=True)
        self.assertTrue(report["clean"])
        self.assertEqual(report["comparison"]["status"], "matched")
        self.assertEqual(report["latest_observed_usage"], counts())

    def test_usage_after_finish_and_null_usage_are_not_lost(self):
        report = audit_stream(sse(chunk(), {"id": "fictional-stream",
            "object": "chat.completion.chunk", "choices": [], "usage": counts()}))
        self.assertTrue(report["clean"])
        self.assertEqual(report["null_usage_events"], 1)
        self.assertEqual(report["latest_observed_usage"]["total_tokens"], 15)

    def test_repeated_snapshots_are_not_added(self):
        report = audit_stream(sse(chunk(counts()), chunk(counts())))
        self.assertTrue(report["clean"])
        self.assertEqual(report["valid_usage_snapshots"], 2)
        self.assertEqual(report["latest_observed_usage"]["total_tokens"], 15)

    def test_zero_is_a_real_observed_count(self):
        report = audit_stream(sse(chunk(counts(0, 0))))
        self.assertTrue(report["clean"])
        self.assertEqual(report["latest_observed_usage"]["total_tokens"], 0)

    def test_missing_usage_remains_unknown(self):
        report = audit_stream(sse(chunk()), saved=counts(0, 0),
                              compare_saved=True, saved_is_usage=True)
        self.assertFalse(report["clean"])
        self.assertIsNone(report["latest_observed_usage"])
        self.assertEqual(report["comparison"]["status"], "capture_usage_unknown")

    def test_cached_and_reasoning_fields_missing_in_saved_are_differences(self):
        value = counts(prompt_tokens_details={"cached_tokens": 4},
                       completion_tokens_details={"reasoning_tokens": 1})
        report = audit_stream(sse(chunk(value)), saved={"usage": counts()}, compare_saved=True)
        self.assertEqual({x["field"] for x in report["comparison"]["differences"]},
                         {"cached_tokens", "reasoning_tokens"})
        self.assertEqual(report["comparison"]["status"], "different")

    def test_missing_saved_usage_and_invalid_counts_are_distinct(self):
        missing = audit_stream(sse(chunk(counts())), saved={}, compare_saved=True)
        bad = audit_stream(sse(chunk(counts())), saved={"usage": counts(True, 3)}, compare_saved=True)
        self.assertEqual(missing["comparison"]["status"], "missing_saved_usage")
        self.assertEqual(bad["comparison"]["status"], "invalid_saved_usage")

    def test_bad_count_types_are_not_accepted(self):
        for value in [True, -1, 1.5, "12", None]:
            with self.subTest(value=value):
                usage = counts()
                usage["prompt_tokens"] = value
                report = audit_stream(sse(chunk(usage)))
                self.assertIsNone(report["latest_observed_usage"])
                self.assertIn("invalid_usage_count", report["issues_by_code"])

    def test_invalid_details_are_not_called_valid_snapshots(self):
        for details in [5, {"cached_tokens": True}, {"cached_tokens": -1}]:
            with self.subTest(details=details):
                report = audit_stream(sse(chunk(counts(prompt_tokens_details=details))))
                self.assertEqual(report["valid_usage_snapshots"], 0)

    def test_inconsistent_totals_and_decreasing_counts_are_reported(self):
        usage = counts()
        usage["total_tokens"] = 99
        report = audit_stream(sse(chunk(usage), chunk(counts(1, 0))))
        self.assertIn("usage_total_mismatch", report["issues_by_code"])
        self.assertIn("usage_count_decreased", report["issues_by_code"])
        self.assertEqual(report["latest_observed_usage"], counts(1, 0))

    def test_detail_larger_than_parent_is_reported(self):
        report = audit_stream(sse(chunk(counts(prompt_tokens_details={"cached_tokens": 13}))))
        self.assertIn("usage_detail_exceeds_parent", report["issues_by_code"])

    def test_missing_finish_and_terminal_markers_are_reported(self):
        report = audit_stream(sse(chunk(counts(), finished=False), done=False))
        self.assertIn("unfinished_choices", report["issues_by_code"])
        self.assertIn("missing_done", report["issues_by_code"])
        self.assertFalse(report["finish_markers_for_observed_choices"])

    def test_single_final_newline_does_not_dispatch_terminal_marker(self):
        text = sse(chunk(counts()), done=False) + "data: [DONE]\n"
        report = audit_stream(text)
        self.assertFalse(report["done_marker_observed"])
        self.assertIn("unterminated_sse_event", report["issues_by_code"])

    def test_unterminated_usage_is_not_used(self):
        report = audit_stream("data: " + json.dumps(chunk(counts())))
        self.assertIsNone(report["latest_observed_usage"])
        self.assertIn("unterminated_sse_event", report["issues_by_code"])

    def test_crlf_cr_bom_comments_and_multiline_data(self):
        text = ": comment\nid: example\nretry: 500\n\ndata: " + json.dumps(chunk(counts()), indent=2).replace("\n", "\ndata: ") + "\n\ndata: [DONE]\n\n"
        for ending in ["\n", "\r\n", "\r"]:
            with self.subTest(ending=repr(ending)):
                self.assertTrue(audit_stream("\ufeff" + text.replace("\n", ending))["clean"])

    def test_unicode_line_separators_are_json_content(self):
        value = chunk(counts())
        value["choices"][0]["delta"]["content"] = "hello\u2028world\u0085next"
        self.assertTrue(audit_stream(sse(value))["clean"])

    def test_strict_json_and_unsupported_profiles(self):
        for text in ['{"a":1,"a":2}', '{"x":NaN}', '{"x":1e999}', '[]', '{"x":"\\ud800"}']:
            with self.subTest(text=text):
                self.assertIn("invalid_data_event",
                              audit_stream("data: " + text + "\n\n")["issues_by_code"])
        self.assertIn("unsupported_chunk", audit_stream(sse({"object": "response.output_text.delta"}))["issues_by_code"])

    def test_provider_errors_do_not_echo_payload(self):
        report = audit_stream(sse({"error": {"message": "PRIVATE_MESSAGE_381"}}))
        self.assertIn("provider_error", report["issues_by_code"])
        self.assertNotIn("PRIVATE_MESSAGE_381", json.dumps(report))

    def test_mixed_ids_are_not_compared_as_one_stream(self):
        report = audit_stream(sse(chunk(counts()), chunk(counts(80, 5), identifier="other")),
                              saved={"usage": counts()}, compare_saved=True)
        self.assertFalse(report["stream_ids_consistent"])
        self.assertEqual(report["latest_observed_usage"], counts())
        self.assertEqual(report["comparison"]["status"], "capture_identity_ambiguous")

    def test_invalid_ids_and_choice_shapes_are_findings(self):
        for update, code in [({"id": ""}, "invalid_stream_id"), ({"choices": {}}, "invalid_choices"),
                ({"choices": [{"index": True}]}, "invalid_choice"),
                ({"choices": [{"index": 0, "finish_reason": False}]}, "invalid_finish_reason"),
                ({"choices": [{"index": 0}, {"index": 0}]}, "duplicate_choice_index")]:
            with self.subTest(code=code):
                value = chunk(counts())
                value.update(update)
                self.assertIn(code, audit_stream(sse(value))["issues_by_code"])

    def test_data_after_done_is_flagged_and_not_used(self):
        report = audit_stream(sse(chunk(counts())) + sse(chunk(counts(90, 9))))
        self.assertIn("data_after_done", report["issues_by_code"])
        self.assertEqual(report["latest_observed_usage"], counts())

    def test_findings_are_bounded_but_counts_continue(self):
        report = audit_stream(sse(*[{}] * 20), max_issues=2)
        self.assertEqual(len(report["issues"]), 2)
        self.assertGreater(report["total_issues"], 20)
        self.assertTrue(report["issue_details_truncated"])

    def test_empty_capture_and_invalid_limits(self):
        self.assertIn("no_data_events", audit_stream("")["issues_by_code"])
        for value in [0, 2001, True]:
            with self.subTest(value=value), self.assertRaises(ToolError):
                audit_stream("", max_issues=value)
        with self.assertRaises(ToolError):
            audit_stream("data: {}\n\n" * (MAX_RECORDS + 1))


class RetryLensTests(unittest.TestCase):
    def test_exact_hint_wait_passes(self):
        report = audit_retries(jsonl(attempt(headers={"Retry-After": "5"}),
                                    attempt(2, start=6, response=7)))
        self.assertTrue(report["clean"])
        self.assertEqual(report["compared_follow_ups"], 1)
        self.assertEqual(report["operations"][0]["transitions"][0]["wait_seconds"], 5)

    def test_wait_is_measured_after_header_receipt(self):
        report = audit_retries(jsonl(attempt(response=5, headers={"retry-after": "5"}),
                                    attempt(2, start=7, response=8)))
        self.assertEqual(report["follow_ups_before_hint"], 1)
        self.assertEqual(report["operations"][0]["transitions"][0]["wait_seconds"], 2)

    def test_http_date_compares_against_recorded_clock(self):
        first = attempt(headers={"ReTrY-AfTeR": "Sat, 17 Oct 2026 00:00:06 GMT"})
        report = audit_retries(jsonl(first, attempt(2, start=5, response=6)))
        self.assertEqual(report["follow_ups_before_hint"], 1)
        self.assertEqual(report["operations"][0]["transitions"][0]["retry_after_seconds"], 5)

    def test_http_date_in_past_means_zero_wait(self):
        report = audit_retries(jsonl(attempt(headers={"retry-after": "Fri, 16 Oct 2026 00:00:06 GMT"}),
                                    attempt(2, start=1, response=2)))
        self.assertTrue(report["clean"])

    def test_millisecond_hints_and_fractional_timestamps(self):
        first, second = attempt(headers={"retry-after-ms": "250.5"}), attempt(2)
        second.update(started_at="2026-10-17T00:00:01.250Z", response_at="2026-10-17T00:00:02Z")
        report = audit_retries(jsonl(first, second))
        self.assertEqual(report["follow_ups_before_hint"], 1)
        self.assertAlmostEqual(report["operations"][0]["transitions"][0]["retry_after_ms_seconds"], .2505)

    def test_conflicting_headers_remain_separate(self):
        report = audit_retries(jsonl(attempt(headers={"Retry-After": "5", "retry-after-ms": "2000"}),
                                    attempt(2, start=4, response=5)))
        observation = report["operations"][0]["transitions"][0]
        self.assertTrue(observation["before_standard_hint"])
        self.assertFalse(observation["before_ms_hint"])
        self.assertIn("conflicting_retry_headers", report["issues_by_code"])

    def test_duplicate_headers_are_ambiguous(self):
        for headers in [{"Retry-After": "1", "retry-after": "1"}, {"retry-after": ["1", "2"]}]:
            with self.subTest(headers=headers):
                report = audit_retries(jsonl(attempt(headers=headers), attempt(2, start=1, response=2)))
                self.assertIn("ambiguous_retry_header", report["issues_by_code"])
                self.assertEqual(report["follow_ups_before_hint"], 0)

    def test_invalid_headers_do_not_echo_values(self):
        for value in ["-5", "1.5", "NaN", "PRIVATE_BAD_HEADER", "9" * 31]:
            with self.subTest(value=value):
                report = audit_retries(jsonl(attempt(headers={"retry-after": value})))
                self.assertIn("invalid_retry_header", report["issues_by_code"])
                if value == "PRIVATE_BAD_HEADER":
                    self.assertNotIn(value, json.dumps(report))

    def test_out_of_order_lines_are_sorted_by_attempt(self):
        report = audit_retries(jsonl(attempt(2, start=6, response=7),
                                    attempt(headers={"retry-after": "5"})))
        self.assertTrue(report["clean"])
        self.assertEqual(report["compared_follow_ups"], 1)

    def test_missing_attempt_numbers_are_not_bridged(self):
        report = audit_retries(jsonl(attempt(), attempt(3, start=2, response=3)))
        self.assertEqual(report["compared_follow_ups"], 0)
        self.assertIn("attempt_gap", report["issues_by_code"])
        self.assertIn("missing_initial_attempt", audit_retries(jsonl(attempt(3)))["issues_by_code"])

    def test_duplicate_attempts_disable_operation_timing(self):
        report = audit_retries(jsonl(attempt(), attempt(), attempt(2, start=6, response=7)))
        self.assertEqual(report["compared_follow_ups"], 0)
        self.assertFalse(report["operations"][0]["timing_comparable"])
        self.assertIn("duplicate_attempt", report["issues_by_code"])

    def test_invalid_row_with_known_id_disables_that_operation(self):
        invalid = attempt(2, start=2, response=3)
        invalid["status_code"] = True
        report = audit_retries(jsonl(attempt(), invalid, attempt(3, start=4, response=5)))
        self.assertEqual(report["compared_follow_ups"], 0)
        self.assertFalse(report["operations"][0]["timing_comparable"])

    def test_overlap_is_observed_without_policy_claim(self):
        report = audit_retries(jsonl(attempt(response=5), attempt(2, start=3, response=6)))
        self.assertEqual(report["overlapping_follow_ups"], 1)
        self.assertEqual(report["follow_ups_before_hint"], 0)

    def test_invalid_record_fields_and_time_order(self):
        for key, value, code in [
            ("operation_id", "", "invalid_operation_id"), ("attempt", True, "invalid_attempt"),
            ("attempt", 0, "invalid_attempt"), ("status_code", 600, "invalid_status"),
            ("started_at", "2026-10-17T00:00:00", "invalid_timestamp"),
            ("started_at", "2026-99-17T00:00:00Z", "invalid_timestamp"),
            ("started_at", "2026-10-17T00:00:02Z", "response_before_start"),
            ("response_headers", {"retry-after": []}, "invalid_headers"),
            ("response_headers", {"retry-after": 5}, "invalid_headers"),
        ]:
            with self.subTest(key=key, value=value):
                row = attempt()
                row[key] = value
                self.assertIn(code, audit_retries(jsonl(row))["issues_by_code"])

    def test_timezone_offsets_represent_same_instant(self):
        first = attempt(headers={"retry-after": "0"})
        first["started_at"] = "2026-10-17T01:00:00+01:00"
        report = audit_retries(jsonl(first, attempt(2, start=1, response=2)))
        self.assertTrue(report["clean"])

    def test_burst_window_is_half_open(self):
        rows = [attempt(operation="a"), attempt(operation="b"), attempt(operation="c", start=1, response=2)]
        report = audit_retries(jsonl(*rows), burst_window_seconds=1)
        self.assertEqual(report["peak_attempt_starts_in_window"], 2)
        self.assertTrue(report["clean"])

    def test_record_payload_and_operation_ids_are_not_reported(self):
        row = attempt(operation="PRIVATE_OPERATION_NAME")
        row["request_body"] = "PRIVATE_PAYLOAD"
        report = audit_retries(jsonl(row))
        self.assertNotIn("PRIVATE_OPERATION_NAME", json.dumps(report))
        self.assertNotIn("PRIVATE_PAYLOAD", json.dumps(report))

    def test_operation_details_are_bounded_with_full_totals(self):
        report = audit_retries(jsonl(*[attempt(operation=str(x)) for x in range(10)]), max_issues=2)
        self.assertEqual(report["operation_count"], 10)
        self.assertEqual(len(report["operations"]), 2)
        self.assertTrue(report["operation_details_truncated"])

    def test_empty_invalid_json_and_limits(self):
        self.assertIn("empty_input", audit_retries("")["issues_by_code"])
        self.assertIn("invalid_record", audit_retries('{"x":NaN}\n')["issues_by_code"])
        for value in [0, -1, 3601, float("nan"), float("inf"), True, 10**1000]:
            with self.subTest(value=str(value)[:20]), self.assertRaises(ToolError):
                audit_retries("", burst_window_seconds=value)
        with self.assertRaises(ToolError):
            audit_retries("\n" * (MAX_RECORDS + 1))


class BatchContractTests(unittest.TestCase):
    def test_valid_input_and_all_profile_endpoints(self):
        for endpoint in endpoints():
            with self.subTest(endpoint=endpoint):
                report = audit_batch(jsonl(batch_input(url=endpoint)), endpoint=endpoint)
                self.assertTrue(report["valid"])
                self.assertEqual(report["accepted_rows"], 1)

    def test_request_body_is_opaque_not_an_api_acceptance_claim(self):
        row = batch_input()
        row["body"] = {"unsupported": True}
        self.assertTrue(audit_batch(jsonl(row))["valid"])

    def test_input_field_types_are_checked(self):
        for key, value in [("custom_id", ""), ("method", "GET"), ("url", "/unknown"), ("url", []),
                           ("body", []), ("custom_id", 8)]:
            with self.subTest(key=key, value=value):
                row = batch_input()
                row[key] = value
                self.assertFalse(audit_batch(jsonl(row))["valid"])

    def test_duplicate_ids_report_first_line_without_values(self):
        row = batch_input("PRIVATE_CUSTOM_ID")
        report = audit_batch(jsonl(row, row))
        self.assertEqual(report["rejected_rows"], 1)
        self.assertEqual(report["issues"][0]["first_line"], 1)
        self.assertNotIn("PRIVATE_CUSTOM_ID", json.dumps(report))

    def test_mixed_endpoints_models_and_selected_endpoint(self):
        first = batch_input()
        second = batch_input("b", url="/v1/responses", model="other-model")
        report = audit_batch(jsonl(first, second), endpoint="/v1/chat/completions")
        self.assertEqual(set(report["issues_by_code"]), {"mixed_endpoints", "mixed_models", "endpoint_mismatch"})

    def test_well_formed_provider_error_is_a_valid_result_and_error(self):
        row = {"id": "example", "custom_id": "a", "response": None,
               "error": {"code": "batch_expired", "message": "PRIVATE_PROVIDER_MESSAGE"}}
        for kind in ["result", "error"]:
            with self.subTest(kind=kind):
                report = audit_batch(jsonl(row), kind=kind)
                self.assertTrue(report["valid"])
                self.assertEqual(report["provider_error_rows"], 1)
                self.assertNotIn("PRIVATE_PROVIDER_MESSAGE", json.dumps(report))

    def test_http_failure_is_valid_error_format(self):
        report = audit_batch(jsonl(batch_result(429)), kind="error")
        self.assertTrue(report["valid"])
        self.assertEqual(report["http_error_rows"], 1)

    def test_success_is_result_but_not_error_kind(self):
        self.assertTrue(audit_batch(jsonl(batch_result()), kind="result")["valid"])
        self.assertFalse(audit_batch(jsonl(batch_result()), kind="error")["valid"])

    def test_missing_null_ambiguous_and_malformed_outcomes(self):
        mutations = [
            {"response": None}, {"response": None, "error": None},
            {"response": [], "error": None},
            {"error": {"code": "bad", "message": "failure"}},
            {"response": None, "error": {"code": "", "message": "failure"}},
            {"response": {"status_code": True, "request_id": None, "body": {}}},
            {"response": {"status_code": 600, "request_id": None, "body": {}}},
            {"response": {"status_code": 200, "body": {}}},
            {"response": {"status_code": 200, "request_id": None, "body": []}},
        ]
        for update in mutations:
            with self.subTest(update=update):
                row = batch_result()
                row.update(update)
                self.assertFalse(audit_batch(jsonl(row), kind="result")["valid"])
        row = batch_result()
        del row["error"]
        self.assertFalse(audit_batch(jsonl(row), kind="result")["valid"])

    def test_integral_number_status_matches_json_schema_integer_semantics(self):
        self.assertTrue(audit_batch(jsonl(batch_result(200.0)), kind="result")["valid"])
        self.assertFalse(audit_batch(jsonl(batch_result(200.5)), kind="result")["valid"])

    def test_strict_json_blank_lines_unicode_and_bom(self):
        for line in ['[]', '{"a":1,"a":2}', '{"x":NaN}', '{"x":"\\ud800"}', ""]:
            with self.subTest(line=line):
                self.assertFalse(audit_batch(line + "\n")["valid"])
        row = batch_input()
        row["body"]["text"] = "one\u2028two\u0085three"
        self.assertTrue(audit_batch("\ufeff" + jsonl(row).replace("\n", "\r\n"))["valid"])

    def test_findings_limit_does_not_change_file_totals(self):
        report = audit_batch(jsonl(*[{}] * 10), max_issues=1)
        self.assertEqual(report["rejected_rows"], 10)
        self.assertGreater(report["total_issues"], 10)
        self.assertEqual(len(report["issues"]), 1)
        self.assertTrue(report["issue_details_truncated"])

    def test_schemas_are_self_contained_and_fresh_copies(self):
        for kind in ["input", "result", "error"]:
            with self.subTest(kind=kind):
                value = schema(kind)
                self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertNotIn('"$ref"', json.dumps(value))
                value["title"] = "changed"
                self.assertNotEqual(schema(kind)["title"], "changed")
        self.assertTrue(record_issues(None, "input"))

    def test_unknown_profile_arguments_and_line_limit(self):
        for kwargs in [{"kind": "custom"}, {"endpoint": "/unknown"}, {"kind": "result", "endpoint": "/v1/responses"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolError):
                audit_batch("", **kwargs)
        with self.assertRaises(ToolError):
            audit_batch("\n" * (MAX_RECORDS + 1))
