"""Measure recorded HTTP retry timing. Never schedules or performs requests."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import math
import re

from .common import ToolError
from .diagnostics import Findings, nonnegative_int, object_rows

STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z")


def _time(value) -> datetime | None:
    if not isinstance(value, str) or not STAMP.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _hint(headers: dict, name: str, received: datetime,
          findings: Findings, line: int) -> float | None:
    values = []
    for key, raw in headers.items():
        if key.lower() == name:
            values.extend(raw if isinstance(raw, list) else [raw])
    if not values:
        return None
    if len(values) != 1:
        findings.add("ambiguous_retry_header", "Retry header occurs more than once",
                     line=line, field="/response_headers/" + name)
        return None
    value = values[0].strip()
    try:
        if name == "retry-after-ms":
            if len(value) > 30 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                raise ValueError
            return float(Decimal(value) / 1000)
        if value.isascii() and value.isdigit():
            if len(value) > 30:
                raise ValueError
            return float(int(value))
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            raise ValueError
        # Obsolete HTTP asctime dates have no explicit zone but mean GMT.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (parsed.astimezone(timezone.utc) - received).total_seconds())
    except (ValueError, TypeError, OverflowError, IndexError):
        findings.add("invalid_retry_header", "Retry header could not be interpreted",
                     line=line, field="/response_headers/" + name)
        return None


def audit_retries(text: str, *, max_issues: int = 200,
                  burst_window_seconds: float = 1.0) -> dict:
    if (isinstance(burst_window_seconds, bool)
            or not isinstance(burst_window_seconds, (int, float))
            or not 0 < burst_window_seconds <= 3600
            or not math.isfinite(burst_window_seconds)):
        raise ToolError("burst_window_seconds must be finite, greater than zero and at most 3600")
    findings = Findings(max_issues)
    physical, rows = object_rows(text, findings)
    groups: dict[str, list[dict]] = {}
    invalid_lines = set()
    for line, row in rows:
        before = findings.total
        identifier = row.get("operation_id")
        if not isinstance(identifier, str) or not identifier:
            findings.add("invalid_operation_id", "operation_id must be a non-empty string",
                         line=line, field="/operation_id", severity="error")
        attempt = row.get("attempt")
        if not nonnegative_int(attempt) or attempt < 1:
            findings.add("invalid_attempt", "attempt must be an integer of at least one",
                         line=line, field="/attempt", severity="error")
        started, received = _time(row.get("started_at")), _time(row.get("response_at"))
        if started is None or received is None:
            findings.add("invalid_timestamp",
                         "Use timezone-aware RFC3339 timestamps with up to six fractional digits",
                         line=line, severity="error")
        elif received < started:
            findings.add("response_before_start", "Response time precedes request start",
                         line=line, severity="error")
        status = row.get("status_code")
        if not nonnegative_int(status) or not 100 <= status <= 599:
            findings.add("invalid_status", "status_code must be an integer from 100 through 599",
                         line=line, field="/status_code", severity="error")
        headers = row.get("response_headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(v, str) and not
            (isinstance(v, list) and v and all(isinstance(x, str) for x in v))
            for v in headers.values()
        ):
            findings.add("invalid_headers",
                         "response_headers must map header names to strings or non-empty string lists",
                         line=line, field="/response_headers", severity="error")
        if findings.total != before:
            invalid_lines.add(line)
            continue
        standard = _hint(headers, "retry-after", received, findings, line)
        milliseconds = _hint(headers, "retry-after-ms", received, findings, line)
        if standard is not None and milliseconds is not None and standard != milliseconds:
            findings.add("conflicting_retry_headers",
                         "Standard and millisecond retry hints differ; neither is silently preferred",
                         line=line)
        groups.setdefault(identifier, []).append({
            "line": line, "attempt": attempt, "started": started, "received": received,
            "status": status, "standard": standard, "milliseconds": milliseconds})

    # Invalid rows with known IDs still make that operation incomplete.
    incomplete = {r.get("operation_id") for line, r in rows
                  if line in invalid_lines and isinstance(r.get("operation_id"), str)}
    operations = []
    starts = []
    transitions = early = overlaps = 0
    for number, (identifier, attempts) in enumerate(groups.items(), 1):
        attempts.sort(key=lambda x: (x["attempt"], x["line"]))
        starts.extend(x["started"] for x in attempts)
        seen = set()
        duplicate = False
        for entry in attempts:
            if entry["attempt"] in seen:
                duplicate = True
                findings.add("duplicate_attempt", "Operation repeats an attempt number",
                             line=entry["line"], operation_number=number, severity="error")
            seen.add(entry["attempt"])
        if duplicate or identifier in incomplete:
            operations.append({"operation_number": number, "records": len(attempts),
                               "timing_comparable": False, "transitions": []})
            continue
        observations = []
        if attempts[0]["attempt"] != 1:
            findings.add("missing_initial_attempt", "First recorded attempt is not number one",
                         line=attempts[0]["line"], operation_number=number)
        for previous, current in zip(attempts, attempts[1:]):
            if current["attempt"] != previous["attempt"] + 1:
                findings.add("attempt_gap", "Consecutive attempt numbers are missing",
                             line=current["line"], operation_number=number)
                continue
            gap = (current["started"] - previous["received"]).total_seconds()
            transitions += 1
            observation = {
                "previous_line": previous["line"], "line": current["line"],
                "wait_seconds": gap, "previous_status_code": previous["status"],
                "retry_after_seconds": previous["standard"],
                "retry_after_ms_seconds": previous["milliseconds"],
                "before_standard_hint": previous["standard"] is not None and gap < previous["standard"],
                "before_ms_hint": previous["milliseconds"] is not None and gap < previous["milliseconds"],
            }
            if gap < 0:
                overlaps += 1
                findings.add("overlapping_attempts", "Next attempt starts before the prior response",
                             line=current["line"], operation_number=number)
            if observation["before_standard_hint"] or observation["before_ms_hint"]:
                early += 1
                findings.add("before_retry_hint", "Observed follow-up starts before a recorded retry hint",
                             line=current["line"], operation_number=number)
            observations.append(observation)
        operations.append({"operation_number": number, "records": len(attempts),
                           "timing_comparable": True, "transitions": observations})
    starts.sort()
    window: deque[datetime] = deque()
    peak = 0
    for stamp in starts:
        while window and (stamp - window[0]).total_seconds() >= burst_window_seconds:
            window.popleft()
        window.append(stamp)
        peak = max(peak, len(window))
    # Bound per-operation retained detail as well as issue detail.
    retained, remaining = [], max_issues
    total_observations = sum(len(x["transitions"]) for x in operations)
    for operation in operations[:max_issues]:
        values = operation["transitions"][:remaining]
        remaining -= len(values)
        retained.append({**operation, "transitions": values})
    return {
        "tool": "RetryLens", "profile": "recorded-http-attempts-v1",
        "clean": findings.total == 0, "physical_lines": physical,
        "valid_records": sum(len(x) for x in groups.values()),
        "operation_count": len(groups), "compared_follow_ups": transitions,
        "follow_ups_before_hint": early, "overlapping_follow_ups": overlaps,
        "burst_window_seconds": burst_window_seconds, "peak_attempt_starts_in_window": peak,
        "operations": retained,
        "operation_details_truncated": len(retained) < len(operations)
            or sum(len(x["transitions"]) for x in retained) < total_observations,
        **findings.report(),
        "scope": "Measures provided timestamps and explicit operation/attempt IDs. "
                 "response_at means header receipt, not body completion. HTTP-date comparisons "
                 "depend on the recording clock. Header hints are checked separately. "
                 "Does not infer operation identity, diagnose a freeze, execute retries or change policy.",
    }
