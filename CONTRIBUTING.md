# Contributing

Run `python -m unittest discover -s tests -v` and `python -m microtools_free.demo` before proposing a change. No runtime dependency installation is needed.

For a bug report, include the command, Python/OS version, expected behavior, observed behavior and a small fictional input that reproduces it. Avoid including real credentials, private logs or private datasets. Redaction pattern detection is limited; a cleaned log alone does not establish that it is shareable.

Keep changes focused on a reproducible file-processing problem. Test meaningful behavior and error paths. Preserve refusal to overwrite files, explicit permission to drop invalid JSONL rows, and clear reporting of redaction limits. A new feature should have a runnable example and documented boundaries.

Contributions are distributed under the repository's MIT licence.
