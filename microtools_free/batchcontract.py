"""Check the bundled, dated Batch JSONL envelope profile."""
from __future__ import annotations

from importlib.resources import files
from functools import lru_cache
import json

from .common import ToolError
from .diagnostics import Findings, object_rows

PROFILE = "openai-batch-envelope-2026-10-17"


@lru_cache(maxsize=3)
def _schema_text(kind: str) -> str:
    if kind not in ("input", "result", "error"):
        raise ToolError("kind must be input, result or error")
    return files("microtools_free").joinpath("schemas", PROFILE, kind + ".json").read_text(encoding="utf-8")


def schema(kind: str) -> dict:
    """Return a fresh copy of a bundled, self-contained JSON Schema."""
    return json.loads(_schema_text(kind))


@lru_cache(maxsize=1)
def endpoints() -> tuple[str, ...]:
    return tuple(schema("input")["properties"]["url"]["enum"])


def _string(value) -> bool:
    return isinstance(value, str) and len(value) > 0


def _status(value) -> bool:
    # JSON Schema integers include mathematically integral numbers such as 200.0.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 100 <= value <= 599 and value % 1 == 0)


def record_issues(row: dict, kind: str) -> list[tuple[str, str, str]]:
    """Fixed field checks, not an arbitrary user-schema evaluation engine."""
    if kind not in ("input", "result", "error"):
        raise ToolError("kind must be input, result or error")
    result = []

    def add(field, code, message):
        result.append((field, code, message))

    if not isinstance(row, dict):
        return [("", "invalid_record", "Expected a JSON object")]
    if not _string(row.get("custom_id")):
        add("/custom_id", "invalid_custom_id", "Expected a non-empty string")
    if kind == "input":
        if row.get("method") != "POST":
            add("/method", "invalid_method", "Profile requires POST")
        if row.get("url") not in endpoints():
            add("/url", "unsupported_url", "URL is outside this dated envelope profile")
        if not isinstance(row.get("body"), dict):
            add("/body", "invalid_body", "Request body must be a JSON object")
        return result
    if not _string(row.get("id")):
        add("/id", "invalid_id", "Expected a non-empty result record ID")
    for key in ("response", "error"):
        if key not in row:
            add("/" + key, "missing_field", "Required envelope field is absent")
    response, error = row.get("response"), row.get("error")
    if response is not None and error is not None:
        add("", "ambiguous_outcome", "Response and error cannot both be non-null")
    elif response is None and error is None:
        add("", "missing_outcome", "Expected a response object or an error object")
    if response is not None:
        if not isinstance(response, dict):
            add("/response", "invalid_response", "Expected a response object or null")
        else:
            status = response.get("status_code")
            if not _status(status):
                add("/response/status_code", "invalid_status", "Expected integer HTTP status 100-599")
            if "request_id" not in response or not (
                response["request_id"] is None or isinstance(response["request_id"], str)
            ):
                add("/response/request_id", "invalid_request_id", "Expected a string or explicit null")
            if not isinstance(response.get("body"), dict):
                add("/response/body", "invalid_response_body", "Expected a JSON object")
    if error is not None:
        if not isinstance(error, dict):
            add("/error", "invalid_error", "Expected an error object or null")
        else:
            for field in ("code", "message"):
                if not _string(error.get(field)):
                    add("/error/" + field, "invalid_error_field", "Expected a non-empty string")
    if kind == "error":
        http_failure = isinstance(response, dict) and _status(response.get("status_code")) and response["status_code"] >= 400
        if error is None and not http_failure:
            add("", "not_error_record", "Error profile needs a provider error or HTTP status at least 400")
    return result


def audit_batch(text: str, *, kind: str = "input", endpoint: str | None = None,
                max_issues: int = 200) -> dict:
    definition = schema(kind)
    allowed = endpoints()
    if endpoint is not None and (kind != "input" or endpoint not in allowed):
        raise ToolError("endpoint is supported only for input and must occur in the dated profile")
    findings = Findings(max_issues)
    physical, rows = object_rows(text, findings)
    ids = {}
    first_url = first_model = None
    valid = provider_errors = http_errors = 0
    for line, row in rows:
        before = findings.total
        for field, code, message in record_issues(row, kind):
            findings.add(code, message, line=line, field=field, severity="error")
        identifier = row.get("custom_id")
        if _string(identifier):
            if identifier in ids:
                findings.add("duplicate_custom_id", "custom_id repeats an earlier row",
                             line=line, field="/custom_id", first_line=ids[identifier], severity="error")
            else:
                ids[identifier] = line
        if kind == "input":
            url = row.get("url")
            if url in allowed:
                if endpoint is not None and url != endpoint:
                    findings.add("endpoint_mismatch", "Row differs from the selected endpoint",
                                 line=line, field="/url", severity="error")
                if first_url is None:
                    first_url = url
                elif url != first_url:
                    findings.add("mixed_endpoints", "Input file contains more than one endpoint",
                                 line=line, field="/url", severity="error")
            body = row.get("body")
            model = body.get("model") if isinstance(body, dict) else None
            if _string(model):
                if first_model is None:
                    first_model = model
                elif model != first_model:
                    findings.add("mixed_models", "Input file contains different explicit model names",
                                 line=line, field="/body/model", severity="error")
        else:
            if isinstance(row.get("error"), dict):
                provider_errors += 1
            response = row.get("response")
            if isinstance(response, dict) and _status(response.get("status_code")) and response["status_code"] >= 400:
                http_errors += 1
        valid += int(before == findings.total)
    return {
        "tool": "BatchContractCheck", "profile": PROFILE, "kind": kind,
        "schema_id": definition["$id"], "valid": findings.total == 0,
        "physical_lines": physical, "parsed_object_rows": len(rows),
        "accepted_rows": valid, "rejected_rows": physical - valid,
        "provider_error_rows": provider_errors, "http_error_rows": http_errors,
        **findings.report(),
        "scope": "Dated OpenAI Batch envelopes, unique custom_id values, and input endpoint/"
                 "explicit-model consistency. Body objects are opaque. A well-formed provider error "
                 "can pass this format check. Does not validate model availability, endpoint-specific "
                 "request parameters, business success, file reconciliation or API acceptance.",
    }
