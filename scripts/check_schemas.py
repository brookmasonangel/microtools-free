"""Development-only comparison with an independent JSON Schema implementation.

Requires jsonschema>=4.23,<5. The seven tools have no runtime dependency on it.
"""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator
from microtools_free.batchcontract import record_issues, schema


def cases():
    """Envelope boundary cases, including each required field and nested type."""
    inputs = [
        {"custom_id": "a", "method": "POST", "url": "/v1/responses", "body": {}},
        {"id": "r", "custom_id": "a", "response": {"status_code": 200, "request_id": None, "body": {}}, "error": None},
        {"id": "r", "custom_id": "a", "response": {"status_code": 429, "request_id": "req", "body": {}}, "error": None},
        {"id": "r", "custom_id": "a", "response": None, "error": {"code": "batch_expired", "message": "fictional"}},
    ]
    paths = [("custom_id",), ("id",), ("method",), ("url",), ("body",), ("response",), ("error",),
             ("response", "status_code"), ("response", "request_id"), ("response", "body"),
             ("error", "code"), ("error", "message")]
    values = [None, False, True, -1, 0, 99, 100, 200, 200.0, 200.5, 399, 400, 599, 600, "",
              "a", "POST", "/v1/responses", [], [{}], {}, {"code": "x", "message": "fictional"},
              {"status_code": 400, "request_id": None, "body": {}}]
    yield from [None, False, 0, [], "text", {}]
    for seed in inputs:
        yield seed
        for path in paths:
            for remove, value in [(True, None)] + [(False, x) for x in values]:
                row = deepcopy(seed)
                parent = row
                for key in path[:-1]:
                    parent = parent.get(key)
                    if not isinstance(parent, dict):
                        break
                if not isinstance(parent, dict):
                    continue
                if remove:
                    parent.pop(path[-1], None)
                else:
                    parent[path[-1]] = value
                yield row


def main():
    comparisons = 0
    for kind in ["input", "result", "error"]:
        definition = schema(kind)
        Draft202012Validator.check_schema(definition)
        validator = Draft202012Validator(definition)
        for index, value in enumerate(cases()):
            expected = validator.is_valid(value)
            actual = not record_issues(value, kind)
            if expected != actual:
                raise AssertionError(f"Schema/checker disagreement for {kind}, case {index}: {value!r}")
            comparisons += 1
    print(f"PASS: {comparisons} independent schema/checker comparisons; three Draft 2020-12 schemas.")


if __name__ == "__main__":
    main()
