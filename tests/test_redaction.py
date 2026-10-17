from __future__ import annotations

import json
import unittest

from microtools_free.common import ToolError
from microtools_free.logredact import MASK, redact


class RedactionTests(unittest.TestCase):
    def test_bearer_and_basic_headers(self):
        source = 'Authorization: Bearer DEMO_VALUE_1234\n"Proxy-Authorization": "Basic ZGVtbzpwYXNz"\n'
        output, report = redact(source)
        self.assertNotIn("DEMO_VALUE_1234", output)
        self.assertNotIn("ZGVtbzpwYXNz", output)
        self.assertEqual(report["redactions"], 2)

    def test_quoted_json_fields_preserve_surrounding_text(self):
        source = json.dumps({"api_key": "DEMO_API_VALUE", "password": "DEMO_PASSWORD", "message": "Keep this"})
        output, _ = redact(source)
        value = json.loads(output)
        self.assertEqual(value, {"api_key": MASK, "password": MASK, "message": "Keep this"})

    def test_escaped_quotes_are_redacted_with_entire_value(self):
        source = json.dumps({"password": 'DEMO_QUOTED_"SECRET"_VALUE', "message": "visible"})
        output, _ = redact(source)
        self.assertEqual(json.loads(output)["password"], MASK)
        self.assertNotIn("SECRET", output)

    def test_environment_assignments_case_and_single_quotes(self):
        output, report = redact("PASSWORD='demo value'\nAPI_KEY=DEMO_API_VALUE\n")
        self.assertEqual(output, "PASSWORD='[REDACTED]'\nAPI_KEY=[REDACTED]\n")
        self.assertEqual(report["redactions"], 2)

    def test_aws_secret_field_and_session_token(self):
        output, report = redact("aws_secret_access_key=DEMO_SECRET_VALUE\naws_session_token=DEMO_SESSION_VALUE\n")
        self.assertNotIn("DEMO_SECRET_VALUE", output)
        self.assertNotIn("DEMO_SESSION_VALUE", output)
        self.assertEqual(report["redactions"], 2)

    def test_recognized_token_prefixes(self):
        # Generated synthetic strings avoid storing anything resembling a real credential.
        examples = ["sk-" + "A" * 24, "ghp_" + "A" * 30, "github_pat_" + "A" * 30, "AKIA" + "A" * 16]
        for value in examples:
            with self.subTest(prefix=value[:4]):
                output, _ = redact("debug " + value + " end")
                self.assertEqual(output, "debug [REDACTED] end")

    def test_url_username_and_password_are_masked(self):
        output, _ = redact("connect=https://demo_user:demo_password@example.test/path")
        self.assertEqual(output, "connect=https://[REDACTED]@example.test/path")

    def test_complete_private_key_block(self):
        value = "-----BEGIN RSA PRIVATE KEY-----\nDEMO_ONLY_NOT_A_KEY\n-----END RSA PRIVATE KEY-----"
        output, report = redact("before\n" + value + "\nafter")
        self.assertEqual(output, "before\n[REDACTED]\nafter")
        self.assertEqual(report["matches_by_rule"]["private_key_block"], 1)

    def test_email_redaction_is_optional(self):
        source = "contact=user@example.test"
        self.assertEqual(redact(source)[0], source)
        self.assertEqual(redact(source, emails=True)[0], "contact=[REDACTED]")

    def test_custom_keys_and_literal_values(self):
        output, report = redact('pin="DEMO_PIN" misc DEMO_LITERAL', extra_keys=["pin"], extra_secrets=["DEMO_LITERAL"])
        self.assertEqual(output, 'pin="[REDACTED]" misc [REDACTED]')
        self.assertEqual(report["redactions"], 2)

    def test_overlapping_matches_are_one_replacement_region(self):
        output, report = redact("api_key=DEMO_SECRET_LONG", extra_secrets=["SECRET"])
        self.assertEqual(output, "api_key=[REDACTED]")
        self.assertEqual(report["redactions"], 1)
        self.assertEqual(report["matches_by_rule"], {"credential_field": 1, "supplied_literal": 1})

    def test_overlapping_literal_occurrences_leave_no_tail(self):
        self.assertEqual(redact("aaaaaa", extra_secrets=["aaaa"])[0], MASK)

    def test_builtin_rules_are_idempotent(self):
        source = 'api_key="DEMO_VALUE"\nAuthorization: Bearer DEMO_TOKEN\nconnect=https://user:pass@example.test/x\n'
        output, _ = redact(source)
        repeated, report = redact(output)
        self.assertEqual(output, repeated)
        self.assertFalse(report["changed"])

    def test_ordinary_text_and_unknown_credentials_remain(self):
        source = "Keep this text.\nunknown_credential=VALUE_NOT_RECOGNIZED\n"
        output, report = redact(source)
        self.assertEqual(output, source)
        self.assertEqual(report["redactions"], 0)

    def test_report_contains_no_matched_values(self):
        _, report = redact("password=DEMO_PRIVATE_VALUE", extra_secrets=["DEMO_PRIVATE_VALUE"])
        self.assertNotIn("DEMO_PRIVATE_VALUE", json.dumps(report))

    def test_json_with_numeric_secret_is_text_redaction_not_validation(self):
        output, _ = redact('{"password":123456,"message":"visible"}')
        self.assertNotIn("123456", output)
        self.assertIn('"message":"visible"', output)

    def test_invalid_custom_keys_and_literals_are_rejected(self):
        for kwargs in [{"extra_keys": [".*"]}, {"extra_secrets": [""]}, {"extra_secrets": ["abc"]}, {"extra_secrets": ["line1\nline2"]}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ToolError):
                redact("text", **kwargs)
