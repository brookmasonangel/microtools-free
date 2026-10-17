"""Small shared helpers for bounded, data-only file diagnostics."""
from __future__ import annotations

from .common import ToolError, canonical, parse_json, require_integer
from .jsonldoctor import physical_lines

MAX_RECORDS = 50000


class Findings:
    def __init__(self, limit: int = 200):
        require_integer(limit, "max_issues", 1, 2000)
        self.limit = limit
        self.items: list[dict] = []
        self.counts: dict[str, int] = {}
        self.total = 0

    def add(self, code: str, message: str, *, line: int | None = None,
            field: str | None = None, severity: str = "warning", **extra) -> None:
        self.total += 1
        self.counts[code] = self.counts.get(code, 0) + 1
        if len(self.items) < self.limit:
            item = {"code": code, "severity": severity, "message": message}
            if line is not None:
                item["line"] = line
            if field is not None:
                item["field"] = field
            self.items.append({**item, **extra})

    def report(self) -> dict:
        return {"total_issues": self.total, "issues_by_code": self.counts,
                "issues": self.items,
                "issue_details_truncated": self.total > len(self.items)}


def strict_object(text: str) -> dict:
    value = parse_json(text)
    canonical(value)  # reject escaped lone surrogates as well as malformed JSON
    if not isinstance(value, dict):
        raise ToolError("Expected a JSON object")
    return value


def object_rows(text: str, findings: Findings) -> tuple[int, list[tuple[int, dict]]]:
    lines = physical_lines(text.removeprefix("\ufeff"))
    if len(lines) > MAX_RECORDS:
        raise ToolError("This diagnostic accepts at most 50,000 physical lines")
    if not lines:
        findings.add("empty_input", "No records found", severity="error")
    records = []
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            findings.add("blank_line", "Expected one JSON object on this line",
                         line=number, severity="error")
            continue
        try:
            value = strict_object(raw)
        except ToolError:
            findings.add("invalid_record", "Invalid strict JSON object",
                         line=number, severity="error")
        else:
            records.append((number, value))
    return len(lines), records


def nonnegative_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
