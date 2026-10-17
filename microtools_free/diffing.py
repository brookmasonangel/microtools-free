from __future__ import annotations

import difflib
import re
from typing import Any

from .common import ToolError, canonical, json_equal, pointer_token, text_hash


def prompt_diff(before: str, after: str, *, before_name: str = "before", after_name: str = "after", ignore_whitespace: bool = False) -> dict:
    transform = lambda text: "\n".join(" ".join(line.split()) for line in text.splitlines()) if ignore_whitespace else text
    left, right = transform(before), transform(after)
    chunks = []
    for line in difflib.unified_diff(left.splitlines(keepends=True), right.splitlines(keepends=True), fromfile=before_name, tofile=after_name, lineterm="\n"):
        if line.endswith("\n"):
            chunks.append(line)
        else:
            chunks.extend([line + "\n", "\\ No newline at end of file\n"])
    return {
        "tool": "PromptDiff", "changed": left != right,
        "comparison": "whitespace_normalized" if ignore_whitespace else "exact_text",
        "before_text_sha256": text_hash(before), "after_text_sha256": text_hash(after),
        "before_characters": len(before), "after_characters": len(after),
        "before_lines": len(before.splitlines()), "after_lines": len(after.splitlines()),
        "diff": "".join(chunks),
    }


def config_diff(before: Any, after: Any, *, ignore: list[str] | None = None) -> dict:
    canonical(before)
    canonical(after)
    paths = ignore or []
    if any(not isinstance(p, str) or (p and not p.startswith("/")) or re.search(r"~(?![01])", p) for p in paths):
        raise ToolError("Ignored fields must be JSON Pointer paths, such as /metadata/time")
    ignored = set(paths)
    changes = []

    def visit(left: Any, right: Any, path: str) -> None:
        if path in ignored:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                child = path + "/" + pointer_token(key)
                if child in ignored:
                    continue
                if key not in left:
                    changes.append({"path": child, "operation": "add", "after": right[key]})
                elif key not in right:
                    changes.append({"path": child, "operation": "remove", "before": left[key]})
                else:
                    visit(left[key], right[key], child)
        elif isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                child = path + "/" + str(index)
                if child in ignored:
                    continue
                if index >= len(left):
                    changes.append({"path": child, "operation": "add", "after": right[index]})
                elif index >= len(right):
                    changes.append({"path": child, "operation": "remove", "before": left[index]})
                else:
                    visit(left[index], right[index], child)
        elif not json_equal(left, right):
            changes.append({"path": path, "operation": "replace", "before": left, "after": right})

    visit(before, after, "")
    return {"tool": "ConfigDiff", "changed": bool(changes), "ignored_paths": sorted(ignored), "changes": changes, "scope": "JSON values; object key order ignored, array order significant"}
