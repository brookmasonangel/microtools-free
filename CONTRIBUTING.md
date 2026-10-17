# Contributing

Run `python -m unittest discover -s tests -v` and `python -m microtools_free.demo` before proposing a change. No runtime dependency installation is needed.

When changing the Batch profile/checker, install the development-only validator with `python -m pip install "jsonschema>=4.23,<5"` and run `python scripts/check_schemas.py`. This compares envelope boundary cases against an independent schema implementation. Preserve the dated schemas' agreement with the fixed field checks. For package changes, install with `python -m pip install .` and run `python scripts/installed_smoke.py` to check imports, bundled resources and all seven commands outside the source directory.

For a bug report, include the command, Python/OS version, expected behavior, observed behavior and a small fictional input that reproduces it. Avoid including real credentials, private logs or private datasets. Redaction pattern detection is limited; a cleaned log alone does not establish that it is shareable.

Keep changes focused on a reproducible file-processing problem. Test meaningful behavior and error paths. Preserve refusal to overwrite files, explicit permission to drop invalid JSONL rows, and clear reporting of redaction limits. A new feature should have a runnable example and documented boundaries.

Contributions are distributed under the repository's MIT licence.
