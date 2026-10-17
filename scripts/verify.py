"""Run the functional checks and optionally retain a machine-readable result."""
from __future__ import annotations

import argparse
import io
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from microtools_free.common import json_text, utc_now, write_new


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = []

    def addSuccess(self, test):
        self.checks.append({"test": test.id(), "result": "passed"})
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.checks.append({"test": test.id(), "result": "failed"})
        super().addFailure(test, err)

    def addError(self, test, err):
        self.checks.append({"test": test.id(), "result": "error"})
        super().addError(test, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new filename")
    started = utc_now()
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=RecordingResult).run(suite)
    report = {"started_at_utc": started, "finished_at_utc": utc_now(), "python": platform.python_version(), "platform": platform.platform(), "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped), "successful": result.wasSuccessful(), "scope": "Local file utilities, CLI, JSONL filtering, redaction patterns and fictional demo checks. No GitHub CI or installed-package checks.", "checks": result.checks, "log": log.getvalue()}
    if args.output:
        write_new(args.output, json_text(report))
    print(json_text({key: report[key] for key in ["python", "tests_run", "failures", "errors", "skipped", "successful"]}), end="")
    if not result.wasSuccessful():
        print(log.getvalue(), file=sys.stderr)
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())

