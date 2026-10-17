"""Redact configured text patterns; never claim comprehensive secret detection."""
from __future__ import annotations

import re

from .common import ToolError, text_hash


MASK = "[REDACTED]"
DEFAULT_KEYS = ["api_key", "api-key", "apikey", "api_secret", "access_token", "access-token", "refresh_token", "refresh-token", "client_secret", "client-secret", "password", "passwd", "secret", "token", "aws_secret_access_key", "aws_session_token", "private_key"]
AUTH = re.compile(r"\b(?:proxy-authorization|authorization)\b[\"']?\s*[:=]\s*[\"']?(?:bearer|basic)\s+(?P<secret>[A-Za-z0-9._~+/=-]+)", re.IGNORECASE)
TOKENS = re.compile(r"(?<![A-Za-z0-9_])(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Za-z0-9_])")
URL_CREDENTIALS = re.compile(r"\b[a-z][a-z0-9+.-]*://(?P<secret>[^\s/@\"']+:[^\s/@\"']+)@", re.IGNORECASE)
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}(?![\w.-])")
PEM = re.compile(r"-----BEGIN (?P<label>(?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY)-----[\s\S]*?-----END (?P=label)-----")


def redact(text: str, *, extra_secrets: list[str] | None = None, extra_keys: list[str] | None = None, emails: bool = False) -> tuple[str, dict]:
    extra_secrets, extra_keys = extra_secrets or [], extra_keys or []
    if len(extra_secrets) > 100 or any(not isinstance(value, str) or not 4 <= len(value) <= 4096 or "\n" in value or "\r" in value or value == MASK for value in extra_secrets):
        raise ToolError("Use at most 100 literal secrets, each 4–4,096 characters on one line; the mask itself is not a secret")
    if len(extra_keys) > 64 or any(not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) is None for key in extra_keys):
        raise ToolError("Use at most 64 additional key names containing letters, digits, underscores or hyphens")
    keys = sorted(set(DEFAULT_KEYS + extra_keys), key=lambda value: (-len(value), value))
    key_pattern = "|".join(re.escape(key) for key in keys)
    fields = re.compile(r"(?<![A-Za-z0-9_-])(?P<quote>[\"']?)(?:" + key_pattern + r")(?P=quote)\s*[:=]\s*(?P<secret>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|[^\s,;}\]\r\n]+)", re.IGNORECASE)
    spans: list[tuple[int, int]] = []
    counts: dict[str, int] = {}

    def add(start: int, end: int, rule: str) -> None:
        if end <= start or text[start:end] == MASK or text.startswith(MASK, start):
            return
        if len(spans) >= 100000:
            raise ToolError("More than 100,000 pattern matches; split this log into smaller files")
        spans.append((start, end))
        counts[rule] = counts.get(rule, 0) + 1

    for rule, pattern in [("authorization_header", AUTH), ("credential_field", fields), ("token_prefix", TOKENS), ("url_credentials", URL_CREDENTIALS), ("private_key_block", PEM)] + ([("email", EMAIL)] if emails else []):
        for match in pattern.finditer(text):
            start, end = match.span("secret") if "secret" in pattern.groupindex else match.span()
            if rule == "credential_field":
                value = text[start:end]
                if value.startswith(("{", "[")) and value != MASK:
                    continue
                if len(value) >= 2 and value[0] in {"\"", "'"} and value[-1] == value[0]:
                    start, end = start + 1, end - 1
            add(start, end, rule)
    for secret in dict.fromkeys(extra_secrets):
        cursor = 0
        while (found := text.find(secret, cursor)) != -1:
            add(found, found + len(secret), "supplied_literal")
            cursor = found + 1
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts, cursor = [], 0
    for start, end in merged:
        parts.extend([text[cursor:start], MASK])
        cursor = end
    parts.append(text[cursor:])
    result = "".join(parts)
    report = {"tool": "LogRedact", "changed": result != text, "redactions": len(merged), "matches_by_rule": counts, "rule_matches_may_overlap": True, "characters_before": len(text), "characters_after": len(result), "redacted_text_sha256": text_hash(result), "email_matching_enabled": emails, "custom_key_count": len(set(extra_keys)), "supplied_literal_count": len(set(extra_secrets)), "scope": "Configured text patterns and supplied literal strings only. Unknown or encoded secrets, private data and unsupported formats may remain. Review the redacted output before sharing; structured format validity is not guaranteed."}
    return result, report
