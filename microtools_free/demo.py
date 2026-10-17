"""Exercise the four utilities with fictional local data and retained reports."""
from __future__ import annotations

import argparse
from pathlib import Path
import uuid

from .common import ToolError, json_text, read_json, read_text, write_new
from .diffing import config_diff, prompt_diff
from .jsonldoctor import audit, filtered_text
from .logredact import redact


def build_demo(destination: Path | None = None) -> dict:
    root = Path(__file__).resolve().parent.parent
    examples = root / "examples"
    destination = destination or root / "demo-output" / uuid.uuid4().hex[:12]
    if destination.exists():
        raise ToolError("Demo destination already exists; choose a new directory")
    destination.mkdir(parents=True)

    def save(name: str, value: dict) -> None:
        write_new(destination / name, json_text(value))

    prompt = prompt_diff(read_text(examples / "prompt-before.txt"), read_text(examples / "prompt-after.txt"))
    save("prompt-diff.json", prompt)
    write_new(destination / "prompt-diff.txt", prompt["diff"])
    config = config_diff(read_json(examples / "config-before.json"), read_json(examples / "config-after.json"), ignore=["/metadata/updated"])
    save("config-diff.json", config)
    valid, _ = audit(read_text(examples / "jobs-valid.jsonl"), required_fields=["id", "prompt"])
    broken, accepted = audit(read_text(examples / "jobs-broken.jsonl"), required_fields=["id", "prompt"])
    save("jsonl-valid.json", valid)
    save("jsonl-broken.json", broken)
    write_new(destination / "accepted-rows.jsonl", filtered_text(accepted))
    redacted, log_report = redact(read_text(examples / "demo.log"), extra_secrets=["DEMO_LITERAL_NOT_REAL"], emails=True)
    write_new(destination / "redacted-demo.log", redacted)
    save("redaction-report.json", log_report)
    checks = {"prompt_changes_detected": prompt["changed"], "two_config_changes_detected": len(config["changes"]) == 2, "valid_jsonl_accepted": valid["valid"] and valid["accepted_rows"] == 2, "four_problem_rows_detected": not broken["valid"] and broken["rejected_rows"] == 4, "two_good_rows_preserved": len(accepted) == 2, "six_redaction_regions": log_report["redactions"] == 6, "ordinary_log_text_preserved": "Keep this text" in redacted}
    result = {"demo": "Micro Tools Free", "mode": "local fictional examples; no network calls", "checks": checks, "all_demo_checks_passed": all(checks.values())}
    save("demo-summary.json", result)
    return {**result, "output_directory": str(destination)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_demo(args.output_dir)
        print(json_text(report), end="")
        return int(not report["all_demo_checks_passed"])
    except (ToolError, OSError) as exc:
        print(f"Demo error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
