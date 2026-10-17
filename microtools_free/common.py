from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ToolError(ValueError):
    """An actionable input or operation error."""


MAX_INPUT_BYTES = 20 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _reject_constant(value: str) -> None:
    raise ToolError(f"Non-finite JSON number is unsupported: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ToolError("JSON exponent produces a non-finite float")
    return result


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToolError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def parse_json(text: str, label: str = "JSON") -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float, object_pairs_hook=_unique_keys)
    except ToolError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ToolError(f"Invalid {label}: {exc}") from exc


def read_text(path: str | Path, *, preserve_bom: bool = False) -> str:
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ToolError(f"Input exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MB: {path.name}")
    try:
        return path.read_bytes().decode("utf-8" if preserve_bom else "utf-8-sig")
    except UnicodeError as exc:
        raise ToolError(f"Use a UTF-8 text file: {path.name}") from exc


def read_json(path: str | Path) -> Any:
    return parse_json(read_text(path), str(path))


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ToolError(f"Value cannot be represented as canonical UTF-8 JSON: {exc}") from exc


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_new(path: str | Path, text: str) -> None:
    """Create without replacing an existing output."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ToolError(f"Output already exists; choose a new filename: {path}") from exc


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        value = parse_json(line, f"JSONL line {number}")
        if not isinstance(value, dict):
            raise ToolError(f"JSONL line {number} must be an object")
        rows.append(value)
    return rows


def require_integer(value: Any, name: str, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        limit = f" through {maximum}" if maximum is not None else " or more"
        raise ToolError(f"{name} must be an integer from {minimum}{limit}")
    return value


def json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return (not isinstance(left, float) or math.isfinite(left)) and (not isinstance(right, float) or math.isfinite(right)) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
