# Recorded-file diagnostics

These tools read local UTF-8 files and produce JSON reports. Their code uses standard-library parsing, date arithmetic and fixed field checks. No external service, credentials or runtime packages are required.

All inputs have a 20 MiB limit. RetryLens and BatchContractCheck accept at most 50,000 physical LF/CRLF-delimited lines; a missing final newline is accepted and blank lines are rejected. An initial UTF-8 BOM is accepted. StreamUsageAudit accepts CR/LF/CRLF SSE framing, at most 500,000 physical lines and 50,000 data events. Unicode line separators inside JSON strings are data.

All three reject duplicate JSON keys, non-finite numbers, malformed JSON and invalid Unicode. Reports retain at most `--max-issues` issue details (default 200, range 1-2,000); totals and exit status still cover the complete scan. Python's standard JSON numeric representation is used. Files above the bounds produce an operational error rather than a partial audit.

Outputs never overwrite existing files. Use `--output new-report.json` to save a report or omit it to print JSON. Exit `0` means no findings under the selected profile; `1` means findings; `2` means invalid arguments, unreadable input or another operational error.

## StreamUsageAudit

### Workflow

1. Obtain an unmodified Chat Completions SSE response body using your own recording method.
2. Run `python -m microtools_free streamusageaudit capture.sse`.
3. Optionally add `--saved response.json` to compare the saved response's top-level `usage` object.
4. If the saved file contains only the usage object, add `--saved-is-usage`.

The tool reads `data:` events whose JSON has `object: "chat.completion.chunk"`, a non-empty string `id` and a `choices` array. Choice indexes must be non-negative integers. A non-null finish reason must be a non-empty string. It records which observed choices have finish markers and whether `[DONE]` was captured.

Comments and other SSE fields are ignored. Multiple data lines in one event are joined with LF. Events need a blank-line terminator: an unterminated final event is reported and excluded from usage/terminal-marker processing. Data after `[DONE]` is reported and excluded. Invalid/different stream IDs are reported; different-ID chunks are excluded, and saved-usage comparison becomes inconclusive.

### Usage rules

Each usage object must provide non-negative integer `prompt_tokens`, `completion_tokens` and `total_tokens`. Booleans are invalid. Optional `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens` are checked when present and non-null. Unknown extra fields are ignored.

The latest snapshot with valid count types is retained. Repeated snapshots are **not added**. Totals differing from prompt plus completion, detail counts exceeding parents and decreasing later core counts are findings. Those numerical inconsistencies remain visible in the retained counts; they are not repaired.

Null/absent usage never becomes zero. A real zero remains zero. Saved comparison checks core counts and any observed cached/reasoning counts; an absent optional count and numeric zero differ.

| Report field | Meaning |
| --- | --- |
| `latest_observed_usage` | Latest counts with valid types, or null when unknown |
| `valid_usage_snapshots` | Snapshots with valid count types, not a sum |
| `done_marker_observed` | A terminated `[DONE]` event was seen |
| `finish_markers_for_observed_choices` | Terminal marker and finish reasons for the choices actually observed |
| `comparison.status` | `not_requested`, `matched`, `different`, `missing_saved_usage`, `invalid_saved_usage`, `capture_usage_unknown` or `capture_identity_ambiguous` |

Reports omit content text, stream IDs and provider error messages. Counts and line numbers remain visible. Captured markers and matching counts do not prove recording completeness, authenticity or billing accuracy. Responses API and other providers' stream formats are excluded.

## RetryLens

### Record contract

One JSON object per recorded attempt:

```json
{"operation_id":"example-operation","attempt":1,"started_at":"2026-10-17T00:00:00Z","response_at":"2026-10-17T00:00:01Z","status_code":429,"response_headers":{"Retry-After":"5"}}
```

| Field | Meaning |
| --- | --- |
| `operation_id` | Required non-empty string grouping one logical operation |
| `attempt` | Required integer at least 1, unique within that operation |
| `started_at` | Required request-start timestamp |
| `response_at` | Required **response-header receipt** timestamp, not body completion |
| `status_code` | Required integer HTTP status 100-599 |
| `response_headers` | Optional object mapping header names to strings or non-empty lists of strings |

Timestamps use timezone-aware RFC3339 form with `T`, seconds, optional 1-6 fractional digits, and `Z` or a numeric `+/-HH:MM` offset. Times are normalized to UTC. Response receipt cannot precede the same request's start. Additional fields are ignored.

This is a normalized record contract. Adapters must preserve header receipt times and assign operation/attempt IDs explicitly. Arbitrary SDK-log parsing and timeouts without a recorded response are outside this profile.

### Timing interpretation

Rows are sorted by attempt number within each operation. A follow-up wait is `next.started_at - previous.response_at`. It is compared only across consecutive attempt numbers. Missing initial attempts and gaps are reported; gaps are not bridged. Duplicate attempt numbers or invalid rows with the same known operation ID disable timing comparisons for that operation.

`Retry-After` accepts a non-negative decimal integer number of seconds or a date interpreted by Python's HTTP/email date parser. Past dates imply zero delay. The nonstandard `retry-after-ms` accepts non-negative decimal milliseconds. Numeric hints are limited to 30 characters. Header names are case insensitive; repeated values/case variants are ambiguous and are not interpreted.

Both hints are reported separately. Conflicting hints produce a finding. A start before either hint is an observation, not proof that a particular SDK violated its policy. A recorded `429` alone does not fail this check. Negative follow-up waits are reported as overlaps.

`--burst-window` selects a width in seconds (greater than zero, at most 3,600; default 1). `peak_attempt_starts_in_window` counts the most valid recorded starts in any half-open window of that width. It includes initial attempts and duplicate records. It does not estimate a fleet or diagnose a retry storm.

Reports omit operation IDs and arbitrary payload/header values. Operation numbers refer to first-seen groups in this file. Operation summaries and transition details are also capped by `--max-issues`; complete totals and `operation_details_truncated` remain available.

Clock synchronization, missing records and adapter accuracy affect conclusions. The tool does not calculate optimal backoff, infer jitter policy, diagnose a freeze, execute retries or change any running application.

## BatchContractCheck

### Dated profile

The profile is `openai-batch-envelope-2026-10-17`. Its directory under `microtools_free/schemas` contains three self-contained JSON Schemas using Draft 2020-12, also usable by standard schema tooling. The command uses fixed field checks; it does not evaluate arbitrary user schemas or download schemas.

| Kind | Required shape |
| --- | --- |
| `input` (default) | Non-empty `custom_id`, `method: "POST"`, supported `url`, object `body` |
| `result` | Non-empty `id`/`custom_id`, explicit `response`/`error`, exactly one non-null outcome |
| `error` | Result envelope plus a non-null provider error or response HTTP status at least 400 |

Response objects require HTTP `status_code` 100-599, `request_id` as string or explicit null, and object `body`. JSON Schema integer semantics apply: `200.0` is integral and accepted, `200.5` and booleans are rejected. Provider errors require non-empty string `code` and `message`. Additional fields are allowed.

Input endpoint values:

```text
/v1/responses
/v1/chat/completions
/v1/embeddings
/v1/completions
/v1/moderations
/v1/images/generations
/v1/images/edits
/v1/videos
```

This list follows the Batch create API reference checked on 17 October 2026; the Batch guide's shorter list may differ. It is a dated local profile, not a live capability lookup.

Duplicate `custom_id` values are rejected with their original line number. IDs are tracked even when the first row has other problems. Input files must use one supported endpoint and cannot contain different explicit, non-empty model names. `--endpoint /v1/responses` additionally checks against the chosen endpoint. Missing/invalid model fields are left to endpoint-specific validation.

Bodies are **opaque JSON objects**. The tool does not check model availability, message syntax, required endpoint parameters, token limits, provider quotas or the provider's larger file-size allowance. It does not join results to inputs, generate retries, submit jobs or certify API acceptance.

A well-formed error record can return `0`: the format passed. `provider_error_rows` and `http_error_rows` summarize recorded failures separately from malformed envelopes. Reports include paths and line numbers; they omit custom IDs, body contents and error messages.

## Public format references

Checked on 17 October 2026; provider documentation can change:

- [Chat Completions streaming and include_usage](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): null usage chunks and a final usage chunk before `[DONE]`; interrupted streams may miss it.
- [WHATWG SSE interpretation](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation): framing and termination.
- [RFC 9110 Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3): seconds or HTTP date.
- [OpenAI Python client's public retry handling](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py): an example of the millisecond hint. RetryLens does not reproduce or enforce that client's policy.
- [Batch guide](https://developers.openai.com/api/docs/guides/batch): file examples, IDs and model consistency.
- [Batch create API reference](https://developers.openai.com/api/reference/resources/batches/methods/create): endpoints and provider limits.

Examples are fictional. These are bounded file diagnostics, not an execution-control system or a general verification framework.
