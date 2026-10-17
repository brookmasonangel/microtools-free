from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .common import ToolError, json_text, read_json, read_text, write_new
from .diffing import config_diff, prompt_diff
from .jsonldoctor import audit, filtered_text, physical_lines
from .logredact import redact
from .streamusage import audit_stream
from .retrylens import audit_retries
from .batchcontract import audit_batch, endpoints


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="microtools-free", description="Seven free local file utilities. Run without third-party packages or network calls.")
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="tool", required=True)
    prompt = sub.add_parser("promptdiff", help="See exactly how two prompt text files differ")
    prompt.add_argument("before"); prompt.add_argument("after")
    prompt.add_argument("--ignore-whitespace", action="store_true")
    prompt.add_argument("--format", choices=["json", "text"], default="json")
    config = sub.add_parser("configdiff", help="Compare JSON settings while ignoring chosen subtrees")
    config.add_argument("before"); config.add_argument("after")
    config.add_argument("--ignore", action="append", default=[], help="Ignore a JSON Pointer subtree, e.g. /metadata/time")
    doctor = sub.add_parser("jsonldoctor", help="Find invalid JSONL rows, missing fields and duplicate string IDs")
    doctor.add_argument("file")
    doctor.add_argument("--require", action="append", default=[], help="Required top-level field name; repeat for more")
    doctor.add_argument("--id-field", default="id")
    doctor.add_argument("--no-id-check", action="store_true")
    doctor.add_argument("--max-issues", type=int, default=200)
    doctor.add_argument("--write-valid", help="Create a separate copy of accepted rows")
    doctor.add_argument("--drop-invalid", action="store_true", help="Explicitly allow rejecting rows when creating a copy")
    logs = sub.add_parser("logredact", help="Mask recognised text patterns and supplied secrets before sharing logs")
    logs.add_argument("file")
    logs.add_argument("--key", action="append", default=[], help="An additional credential field name")
    logs.add_argument("--secrets-file", help="UTF-8 file with one literal secret per non-empty line")
    logs.add_argument("--emails", action="store_true", help="Also mask addresses matched by the email pattern")
    logs.add_argument("--preview", action="store_true", help="Print the redacted text; otherwise print summary only")
    logs.add_argument("--report", help="Create a separate summary JSON file containing no matched values")
    stream = sub.add_parser("streamusageaudit", help="Inspect usage snapshots in a captured Chat Completions SSE file")
    stream.add_argument("file")
    stream.add_argument("--saved", help="Optional saved response JSON to compare with captured usage")
    stream.add_argument("--saved-is-usage", action="store_true", help="Treat --saved as a usage object instead of a response")
    retry = sub.add_parser("retrylens", help="Measure retry waits and bursts in recorded HTTP-attempt JSONL")
    retry.add_argument("file")
    retry.add_argument("--burst-window", type=float, default=1.0, help="Window width in seconds, greater than zero and at most 3600")
    batch = sub.add_parser("batchcontractcheck", help="Check Batch JSONL against bundled, dated envelope profiles")
    batch.add_argument("file")
    batch.add_argument("--kind", choices=["input", "result", "error"], default="input")
    batch.add_argument("--endpoint", choices=endpoints(), help="Expected endpoint for an input file")
    for command in [stream, retry, batch]:
        command.add_argument("--max-issues", type=int, default=200)
    for command in [prompt, config, doctor, stream, retry, batch]:
        command.add_argument("--output", help="Create a new report file; otherwise print to terminal")
    logs.add_argument("--output", help="Create a new redacted log file; original is preserved")
    return root


def preflight(paths: list[str | None]) -> None:
    resolved = set()
    for raw in paths:
        if raw is None:
            continue
        path = Path(raw)
        if path.exists() or path.is_symlink():
            raise ToolError(f"Output already exists; choose a new filename: {path}")
        target = path.resolve()
        if target in resolved:
            raise ToolError("Each output needs a different filename")
        resolved.add(target)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.tool == "logredact":
            preflight([args.output, args.report])
            secrets = [line for line in physical_lines(read_text(args.secrets_file)) if line.strip()] if args.secrets_file else []
            cleaned, report = redact(read_text(args.file), extra_secrets=secrets, extra_keys=args.key, emails=args.emails)
            if args.output:
                write_new(args.output, cleaned)
            if args.report:
                write_new(args.report, json_text(report))
            if args.preview:
                print(cleaned, end="" if cleaned.endswith("\n") else "\n")
            else:
                print(json_text(report), end="")
            return 0
        preflight([args.output, getattr(args, "write_valid", None)])
        rendered = None
        if args.tool == "promptdiff":
            report = prompt_diff(read_text(args.before), read_text(args.after), before_name=args.before, after_name=args.after, ignore_whitespace=args.ignore_whitespace)
            code = int(report["changed"])
            if args.format == "text":
                rendered = report["diff"] or "No differences under the selected comparison mode.\n"
        elif args.tool == "configdiff":
            report = config_diff(read_json(args.before), read_json(args.after), ignore=args.ignore)
            code = int(report["changed"])
        elif args.tool == "streamusageaudit":
            if args.saved_is_usage and not args.saved:
                raise ToolError("--saved-is-usage requires --saved")
            report = audit_stream(read_text(args.file), saved=read_json(args.saved) if args.saved else None,
                                  compare_saved=bool(args.saved), saved_is_usage=args.saved_is_usage,
                                  max_issues=args.max_issues)
            code = int(not report["clean"])
        elif args.tool == "retrylens":
            report = audit_retries(read_text(args.file), max_issues=args.max_issues,
                                   burst_window_seconds=args.burst_window)
            code = int(not report["clean"])
        elif args.tool == "batchcontractcheck":
            report = audit_batch(read_text(args.file), kind=args.kind, endpoint=args.endpoint,
                                 max_issues=args.max_issues)
            code = int(not report["valid"])
        else:
            if args.drop_invalid and not args.write_valid:
                raise ToolError("--drop-invalid requires --write-valid")
            report, accepted = audit(read_text(args.file, preserve_bom=True), required_fields=args.require, id_field=None if args.no_id_check else args.id_field, max_issues=args.max_issues)
            code = int(not report["valid"])
            if args.write_valid:
                if not report["valid"] and not args.drop_invalid:
                    raise ToolError("Input has rejected rows. Inspect the audit first, then use --drop-invalid to explicitly create a filtered copy")
                write_new(args.write_valid, filtered_text(accepted))
                report["filtered_copy"] = {"rows_written": len(accepted), "rows_dropped": report["rejected_rows"], "normalization": "UTF-8 without BOM, LF line endings, final newline on non-empty copies"}
        text = rendered if rendered is not None else json_text(report)
        if args.output:
            write_new(args.output, text)
            print(f"Created report: {args.output}")
        else:
            print(text, end="" if text.endswith("\n") else "\n")
        return code
    except (ToolError, OSError, UnicodeError, RecursionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
