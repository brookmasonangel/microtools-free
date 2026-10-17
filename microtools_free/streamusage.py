"""Inspect captured OpenAI Chat Completions SSE usage without making requests."""
from __future__ import annotations

import re

from .common import ToolError
from .diagnostics import Findings, MAX_RECORDS, nonnegative_int, strict_object

PROFILE = "openai-chat-completions-sse-v1"
CORE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _usage(value, findings: Findings, *, line=None, source="capture") -> dict | None:
    prefix = "" if source == "capture" else "saved_"
    if not isinstance(value, dict):
        findings.add(prefix + "invalid_usage", "Usage must be an object",
                     line=line, severity="error")
        return None
    result = {}
    for field in CORE_FIELDS:
        if field not in value or not nonnegative_int(value[field]):
            findings.add(prefix + "invalid_usage_count",
                         "Expected a non-negative integer count",
                         line=line, field="/usage/" + field, severity="error")
        else:
            result[field] = value[field]
    if len(result) != len(CORE_FIELDS):
        return None
    if result["total_tokens"] != result["prompt_tokens"] + result["completion_tokens"]:
        findings.add(prefix + "usage_total_mismatch",
                     "Reported total differs from prompt plus completion counts", line=line)
    details_valid = True
    for container, key, maximum in [
        ("prompt_tokens_details", "cached_tokens", "prompt_tokens"),
        ("completion_tokens_details", "reasoning_tokens", "completion_tokens"),
    ]:
        details = value.get(container)
        if details is None:
            continue
        if not isinstance(details, dict):
            details_valid = False
            findings.add(prefix + "invalid_usage_details",
                         "Expected an object or null for usage details",
                         line=line, field="/usage/" + container, severity="error")
        elif key in details and details[key] is not None:
            if not nonnegative_int(details[key]):
                details_valid = False
                findings.add(prefix + "invalid_usage_count",
                             "Expected a non-negative integer count",
                             line=line, field="/usage/" + container + "/" + key,
                             severity="error")
            else:
                result[key] = details[key]
                if details[key] > result[maximum]:
                    findings.add(prefix + "usage_detail_exceeds_parent",
                                 "Detail count exceeds its parent count",
                                 line=line, field="/usage/" + container + "/" + key)
    return result if details_valid else None


def audit_stream(text: str, *, saved=None, compare_saved: bool = False,
                 saved_is_usage: bool = False, max_issues: int = 200) -> dict:
    findings = Findings(max_issues)
    # SSE recognizes CR, LF and CRLF. Unicode line separators in JSON are data.
    lines = re.split(r"\r\n|\r|\n", text.removeprefix("\ufeff"))
    if lines[-1] == "":
        lines.pop()  # A trailing line ending is not an extra blank line.
    if len(lines) > MAX_RECORDS * 10:
        raise ToolError("Stream capture exceeds 500,000 physical lines")
    events = []
    data: list[str] = []
    first_line = None
    for number, raw in enumerate(lines, 1):
        if not raw:
            if data:
                events.append((first_line, "\n".join(data), True))
                data, first_line = [], None
        elif raw.startswith(":"):
            continue
        else:
            field, separator, value = raw.partition(":")
            if field == "data":
                if first_line is None:
                    first_line = number
                data.append(value[1:] if value.startswith(" ") else value)
        if len(events) > MAX_RECORDS:
            raise ToolError("Stream capture exceeds 50,000 data events")
    if data:
        events.append((first_line, "\n".join(data), False))
    if len(events) > MAX_RECORDS:
        raise ToolError("Stream capture exceeds 50,000 data events")
    if not events:
        findings.add("no_data_events", "No SSE data events found", severity="error")

    done = False
    latest = None
    latest_line = None
    valid_usage_events = chunks = null_usage_events = 0
    stream_id = None
    identity_consistent = True
    seen_choices: set[int] = set()
    finished_choices: set[int] = set()
    for line, payload, terminated in events:
        if not terminated:
            findings.add("unterminated_sse_event",
                         "Capture ends before the event's blank-line terminator", line=line)
            continue  # SSE does not dispatch an unterminated event.
        if done:
            findings.add("data_after_done", "Data occurs after the terminal marker", line=line)
            continue
        if payload == "[DONE]":
            done = True
            continue
        try:
            chunk = strict_object(payload)
        except ToolError:
            findings.add("invalid_data_event", "Expected a strict JSON object in this event",
                         line=line, severity="error")
            continue
        if chunk.get("error") is not None:
            findings.add("provider_error", "Capture contains a provider error object",
                         line=line, severity="error")
            continue
        if chunk.get("object") != "chat.completion.chunk":
            findings.add("unsupported_chunk",
                         "Expected the documented Chat Completions chunk profile",
                         line=line, severity="error")
            continue
        identifier = chunk.get("id")
        if not isinstance(identifier, str) or not identifier:
            identity_consistent = False
            findings.add("invalid_stream_id", "Chunk ID must be a non-empty string",
                         line=line, severity="error")
            continue
        elif stream_id is None:
            stream_id = identifier
        elif identifier != stream_id:
            identity_consistent = False
            findings.add("mixed_stream_ids", "Capture contains more than one stream ID",
                         line=line, severity="error")
            continue
        chunks += 1
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            findings.add("invalid_choices", "Chunk choices must be an array",
                         line=line, severity="error")
        else:
            indexes = set()
            for choice in choices:
                if not isinstance(choice, dict) or not nonnegative_int(choice.get("index")):
                    findings.add("invalid_choice", "Choice needs a non-negative integer index",
                                 line=line, severity="error")
                    continue
                index = choice["index"]
                if index in indexes:
                    findings.add("duplicate_choice_index",
                                 "Chunk repeats a choice index", line=line, severity="error")
                indexes.add(index)
                seen_choices.add(index)
                finish = choice.get("finish_reason")
                if finish is not None:
                    if not isinstance(finish, str) or not finish:
                        findings.add("invalid_finish_reason",
                                     "Finish reason must be a non-empty string or null",
                                     line=line, severity="error")
                    else:
                        finished_choices.add(index)
        if "usage" in chunk and chunk["usage"] is None:
            null_usage_events += 1
        elif "usage" in chunk:
            counts = _usage(chunk["usage"], findings, line=line)
            if counts is not None:
                valid_usage_events += 1
                if latest is not None and any(counts[k] < latest[k] for k in CORE_FIELDS):
                    findings.add("usage_count_decreased",
                                 "A later usage snapshot has a smaller core count", line=line)
                latest, latest_line = counts, line

    if not done:
        findings.add("missing_done", "Terminal [DONE] marker was not captured")
    if not seen_choices:
        findings.add("no_choices_observed", "No indexed choice was observed")
    elif seen_choices - finished_choices:
        findings.add("unfinished_choices", "A captured choice has no finish reason")
    if latest is None:
        findings.add("missing_capture_usage",
                     "No valid usage snapshot was captured; missing does not mean zero")

    comparison = {"requested": compare_saved, "status": "not_requested", "differences": []}
    if compare_saved:
        value = saved if saved_is_usage else saved.get("usage") if isinstance(saved, dict) else None
        if value is None:
            findings.add("missing_saved_usage", "Saved record has no non-null usage object")
            comparison["status"] = "missing_saved_usage"
        else:
            saved_counts = _usage(value, findings, source="saved")
            comparison["saved_usage"] = saved_counts
            if saved_counts is None:
                comparison["status"] = "invalid_saved_usage"
            elif not identity_consistent:
                comparison["status"] = "capture_identity_ambiguous"
            elif latest is None:
                comparison["status"] = "capture_usage_unknown"
            else:
                for field in sorted(latest.keys() | saved_counts.keys()):
                    if latest.get(field) != saved_counts.get(field):
                        comparison["differences"].append({
                            "field": field, "captured": latest.get(field),
                            "saved": saved_counts.get(field)})
                comparison["status"] = "different" if comparison["differences"] else "matched"
                if comparison["differences"]:
                    findings.add("usage_not_preserved",
                                 "Captured and saved usage fields differ or are missing")
    complete_markers = done and bool(seen_choices) and not (seen_choices - finished_choices)
    return {
        "tool": "StreamUsageAudit", "profile": PROFILE,
        "clean": findings.total == 0, "data_events": len(events), "chunks": chunks,
        "done_marker_observed": done, "finish_markers_for_observed_choices": complete_markers,
        "stream_ids_consistent": identity_consistent,
        "null_usage_events": null_usage_events, "valid_usage_snapshots": valid_usage_events,
        "latest_observed_usage": latest, "latest_usage_line": latest_line,
        "comparison": comparison, **findings.report(),
        "scope": "Recorded Chat Completions SSE only. Uses the latest valid usage snapshot; "
                 "snapshots are not added. Does not recover missing counts, estimate a bill, "
                 "authenticate captures or establish that an entire request was recorded.",
    }
