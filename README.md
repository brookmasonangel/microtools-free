# Micro Tools Free

Seven free local utilities for technical workflow files: text and configuration differences, JSONL checks, log redaction, captured stream usage, recorded HTTP retry timing and Batch file envelopes.

[Download source ZIP](https://github.com/brookmasonangel/microtools-free/archive/refs/heads/main.zip) | [Current GitHub checks](https://github.com/brookmasonangel/microtools-free/actions/workflows/tests.yml)

![Tests](https://github.com/brookmasonangel/microtools-free/actions/workflows/tests.yml/badge.svg)

Python 3.11+. No third-party runtime packages, account, API key or network calls. MIT licensed.

| Tool | Problem it solves | Command |
| --- | --- | --- |
| PromptDiff | What changed between two prompt drafts? | `promptdiff` |
| ConfigDiff | Which JSON settings changed after ignoring selected metadata? | `configdiff` |
| JSONLDoctor | Which rows are malformed, missing fields or repeating IDs? | `jsonldoctor` |
| LogRedact | Which recognised credentials can I mask before sharing this log? | `logredact` |
| StreamUsageAudit | Did captured response-stream usage survive into a saved record? | `streamusageaudit` |
| RetryLens | Did recorded follow-ups start before retry hints, and how concentrated were the starts? | `retrylens` |
| BatchContractCheck | Does this Batch JSONL file follow a dated envelope profile? | `batchcontractcheck` |

## Try it in one minute

Extract the full download into a writable folder and open a terminal in that folder. On Windows, double-click `Run-Demo.cmd`, or run:

```powershell
py -3 -m microtools_free.demo
py -3 -m microtools_free --help
```

The demo creates a new directory under `demo-output`, prints its location, and demonstrates both valid and deliberately broken files. All credential-looking examples are fictional. `sample-output` contains retained example reports.

On macOS/Linux, replace `py -3` with `python3`. The GitHub workflow covers Ubuntu and Windows; macOS is not in the matrix. Local results were collected on Windows. `Open-Tools.cmd` opens a Windows command prompt in the correct folder. Python must already be installed; the launchers are not executable installers.

## PromptDiff

```powershell
py -3 -m microtools_free promptdiff examples/prompt-before.txt examples/prompt-after.txt --format text
py -3 -m microtools_free promptdiff examples/prompt-before.txt examples/prompt-after.txt --output prompt-report.json
```

Exact decoded text is compared by default, including line endings and the final newline. `--ignore-whitespace` collapses whitespace within each line and normalizes line endings/final-newline differences. Raw decoded-text hashes remain in the report. The tool compares text; it does not grade whether a prompt produces better responses.

## ConfigDiff

```powershell
py -3 -m microtools_free configdiff examples/config-before.json examples/config-after.json --ignore /metadata/updated
```

Reports added, removed and replaced JSON values with JSON Pointer paths. Object key order is ignored; array order matters. Numeric `1` and `1.0` compare equally; boolean `true` remains distinct from numeric `1`. Repeat `--ignore` for more subtrees. Escape `~` as `~0` and `/` as `~1` inside pointer tokens. JSON only; YAML/TOML parsing is not included.

## JSONLDoctor

```powershell
py -3 -m microtools_free jsonldoctor examples/jobs-broken.jsonl --require id --require prompt
py -3 -m microtools_free jsonldoctor examples/jobs-valid.jsonl --require id --require prompt --output audit.json
```

Checks every LF/CRLF-delimited row for strict JSON and top-level object form. Blank lines are rejected. Required fields are checked for top-level presence, not value type or inferred schema. A present `id` must be a non-empty string and must not duplicate an earlier ID. Missing `id` is permitted unless `--require id` is given. Use `--id-field record_id` to change the name, or `--no-id-check` to disable ID checks.

The report includes original line numbers, total issue counts, and the first line for duplicated IDs. It does not dump row values or ID values. `--max-issues` controls retained detail (default 200, maximum 2,000); total counts and failure status still cover the complete audit. Duplicate JSON keys, non-finite numbers and invalid Unicode are rejected. The limit is 100,000 physical lines within the 20 MB input limit.

A separately filtered copy is optional:

```powershell
py -3 -m microtools_free jsonldoctor examples/jobs-broken.jsonl --require id --require prompt --write-valid accepted.jsonl --drop-invalid
```

`--drop-invalid` explicitly permits excluding rejected rows. Without it, invalid input prevents copy creation. The original is preserved. Accepted row text, key order and numeric spelling are retained; output uses UTF-8 without a BOM, LF endings and a final newline. Repeated IDs keep the first otherwise accepted occurrence; later duplicate rows are rejected. IDs are tracked even when an earlier row has other issues, so both rows can be rejected if the first fails another check. No guessed repairs are made. The input audit still exits `1` when it found issues, even if a filtered copy was created.

## LogRedact

```powershell
py -3 -m microtools_free logredact examples/demo.log
py -3 -m microtools_free logredact examples/demo.log --preview --emails --secrets-file examples/demo-secrets.txt
py -3 -m microtools_free logredact examples/demo.log --emails --secrets-file examples/demo-secrets.txt --output redacted.log --report redaction-summary.json
```

By default it prints a summary, not the log. `--preview` prints redacted text. `--output` creates a separate redacted log; `--report` creates a JSON summary. Both refuse existing filenames. Neither the original matched values nor supplied secret values are included in the summary.

Patterns cover bearer/basic authorization headers, named credential fields, selected token prefixes, URL username/password pairs, and complete supported private-key blocks. Credential keys include API keys, access/refresh tokens, client secrets, passwords, AWS secret/session fields and private keys. `--key pin` adds a field name. `--emails` enables a common-address pattern; it is not a complete email-address parser.

`--secrets-file` accepts up to 100 literal values, one per non-empty UTF-8 line, each 4â€“4,096 characters. No comment syntax is used. Literal strings are matched exactly, not as regex. Add such files under `local-data` when using Git locally.

Overlapping matches form one replacement region. Per-rule match counts can overlap; `redactions` counts actual replacement regions. At most 100,000 pattern matches are accepted per operation.

**This is a text redactor with documented patterns, not comprehensive secret or personal-data detection.** Unknown credentials, encoded keys, unsupported formats and other private data can remain. Numeric/unquoted values can lose structured-format validity after replacement. A successful exit means redaction completed; it does not certify that a log is safe to disclose. Review the output before sharing it.

## StreamUsageAudit

```powershell
py -3 -m microtools_free streamusageaudit examples/stream-complete.sse
py -3 -m microtools_free streamusageaudit examples/stream-complete.sse --saved examples/stream-saved.json
```

Reads a previously captured OpenAI Chat Completions SSE response body. Checks observed finish/terminal markers and token-count fields, then optionally compares them with a saved response's `usage` object. It uses the latest snapshot with valid count types, never adds snapshots together, and keeps missing counts distinct from zero. The second example deliberately detects lost cached/reasoning fields and exits `1`.

This release supports that SSE profile only. It does not capture traffic, call an API, recover absent usage, calculate bills or establish that a complete request was recorded. See [input formats and limits](docs/DIAGNOSTICS.md#streamusageaudit).

## RetryLens

```powershell
py -3 -m microtools_free retrylens examples/retry-attempts.jsonl
py -3 -m microtools_free retrylens examples/retry-attempts.jsonl --burst-window 2 --output retry-report.json
```

Reads normalized JSONL with explicit operation IDs, attempt numbers, request-start timestamps, response-header receipt timestamps, HTTP statuses and optional response headers. Measures consecutive follow-up waits against `Retry-After` seconds/dates and the nonstandard `retry-after-ms` hint. Counts peak attempt starts within a selected window. The example records a follow-up before its hint and exits `1`.

It measures supplied records; it does not infer retry identities, parse arbitrary SDK logs, schedule requests, diagnose freezes or change retry policy. See the [record contract and clock assumptions](docs/DIAGNOSTICS.md#retrylens).

## BatchContractCheck

```powershell
py -3 -m microtools_free batchcontractcheck examples/batch-input.jsonl
py -3 -m microtools_free batchcontractcheck examples/batch-results.jsonl --kind result
```

Checks strict JSON objects, envelope field types and duplicate `custom_id` values. Input files are also checked for consistent endpoints and explicit model names. Three self-contained JSON Schemas are bundled under profile `openai-batch-envelope-2026-10-17`, for `input`, `result` and `error` files.

Request/response body objects remain opaque. A well-formed provider error can pass the result/error format check; that does not mean the request succeeded. Model availability, endpoint-specific parameters, input/output reconciliation and API submission are outside this tool. See [profile details](docs/DIAGNOSTICS.md#batchcontractcheck).

## Output behavior and limits

Inputs are UTF-8, with an optional initial BOM, and limited to 20 MB each. Filesystem writes create new outputs and never replace an existing file. Parent output directories may be created. Multiple output files are not a single atomic transaction; a later disk/write failure can leave an earlier output created.

Exit codes:

- `0`: no differences, a clean/valid diagnostic, or a completed redaction.
- `1`: prompt/config differences or diagnostic findings.
- `2`: invalid arguments/input or an operational error.

Differences and intentionally broken examples returning `1` are expected behavior. JSON numbers use Python's standard integer/float parsing; this is not an arbitrary-precision parser for JSON decimals. Hashes describe local text integrity, not independent signing or authenticity. The tools have no remote service or telemetry.

## Tests and evidence

```powershell
py -3 -m unittest discover -s tests -v
py -3 scripts/verify.py --output local-test-results.json
```

Version 0.2.0 passed 119 functional tests locally on Windows with Python 3.14.3, with zero failures, errors or skips. The [retained result](verification/python-3.14-v0.2.0.json) includes individual test names and the log. Tests cover all seven tools, CLI exit codes, refusal to overwrite inputs/outputs, malformed and truncated data, usage comparison, retry timing and Batch formats. The demo exercises all seven with fictional data.

The current GitHub workflow runs on Ubuntu/Windows with Python 3.11, 3.13 and 3.14. In addition to the tests and demo, it compares the fixed Batch field checks with an independent JSON Schema implementation, installs the package, and exercises all seven installed commands outside the checkout. The validator is a development-only dependency. See [live results](https://github.com/brookmasonangel/microtools-free/actions/workflows/tests.yml) for completed executions. Older files in `verification` with 55 tests describe the previous four-tool version, not the new three tools.

Run directly from the extracted source folder, or install from that folder:

```powershell
py -3 -m pip install .
microtools-free --help
```

Installation uses setuptools as a build dependency. The installed runtime has no third-party dependencies. Schemas are included in the installed package; examples, the source-tree demo and test scripts are supplied in the source download.

## Publish and contribute

See [GitHub upload steps](docs/GITHUB_UPLOAD.md) for the browser route. The source is MIT licensed; see [LICENSE](LICENSE). Source publication and commercial reuse are permitted by that licence.

Bug reports should include a minimal fictional example, command, expected result, actual result, and Python/OS version. See [CONTRIBUTING.md](CONTRIBUTING.md). Functional checks do not establish adoption, customer demand or suitability for every production workflow.
