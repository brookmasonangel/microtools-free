"""Inspect every JSONL row and prepare an explicitly filtered copy."""
from __future__ import annotations

from .common import ToolError, canonical, parse_json, require_integer, text_hash


def physical_lines(text: str) -> list[str]:
    """Split only LF/CRLF; Unicode separators inside JSON strings are data."""
    if not text:
        return []
    rows = text.split("\n")
    if rows[-1] == "":
        rows.pop()
    return [line[:-1] if line.endswith("\r") else line for line in rows]


def audit(text: str, *, required_fields: list[str] | None = None, id_field: str | None = "id", max_issues: int = 200) -> tuple[dict, list[str]]:
    require_integer(max_issues, "max_issues", 1, 2000)
    required_fields = required_fields or []
    if len(required_fields) > 64 or any(not isinstance(field, str) or not field for field in required_fields):
        raise ToolError("Use at most 64 non-empty top-level required field names")
    if id_field is not None and (not isinstance(id_field, str) or not id_field):
        raise ToolError("id_field must be a non-empty field name or None")
    source_hash = text_hash(text)
    bom = text.startswith("\ufeff")
    if bom:
        text = text[1:]
    lines = physical_lines(text)
    if len(lines) > 100000:
        raise ToolError("JSONL audit accepts at most 100,000 physical lines")
    issues, accepted, ids = [], [], {}
    counts: dict[str, int] = {}
    invalid = blank = parsed = total_issues = 0

    def issue(line: int | None, code: str, message: str, **extra) -> None:
        nonlocal total_issues
        total_issues += 1
        counts[code] = counts.get(code, 0) + 1
        if len(issues) < max_issues:
            issues.append({"line": line, "code": code, "message": message, **extra})

    if not lines:
        issue(None, "empty_input", "No JSONL records found")
    for number, raw in enumerate(lines, 1):
        start_issues = total_issues
        if not raw.strip():
            blank += 1
            issue(number, "blank_line", "Blank lines are not JSON records")
        else:
            try:
                row = parse_json(raw, f"JSONL line {number}")
                canonical(row)
            except ToolError as exc:
                issue(number, "invalid_json", str(exc))
            else:
                parsed += 1
                if not isinstance(row, dict):
                    issue(number, "not_object", "Expected a JSON object")
                else:
                    for field in dict.fromkeys(required_fields):
                        if field not in row:
                            issue(number, "missing_field", "Required top-level field is absent", field=field)
                    if id_field is not None and id_field in row:
                        identifier = row[id_field]
                        if not isinstance(identifier, str) or not identifier:
                            issue(number, "invalid_id", "Present IDs must be non-empty strings", field=id_field)
                        elif identifier in ids:
                            issue(number, "duplicate_id", "ID duplicates an earlier record", field=id_field, first_line=ids[identifier])
                        else:
                            ids[identifier] = number
        if total_issues != start_issues:
            invalid += 1
        else:
            accepted.append(raw)
    report = {"tool": "JSONLDoctor", "valid": total_issues == 0, "physical_lines": len(lines), "parsed_json_rows": parsed, "accepted_rows": len(accepted), "rejected_rows": invalid, "blank_lines": blank, "total_issues": total_issues, "issues_by_code": counts, "issues": issues, "issue_details_truncated": total_issues > len(issues), "required_fields": list(dict.fromkeys(required_fields)), "id_field": id_field, "utf8_bom_accepted": bom, "trailing_newline": bool(text) and text.endswith("\n"), "source_text_sha256": source_hash, "scope": "Object rows, strict JSON, optional top-level field presence and string ID checks. No schema inference or guessed repairs; input row contents are not included in this report."}
    return report, accepted


def filtered_text(accepted: list[str]) -> str:
    """Preserve accepted row text; normalize CRLF to LF and add final LF."""
    return "\n".join(accepted) + ("\n" if accepted else "")
