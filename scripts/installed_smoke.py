"""Exercise an installed package from outside the source tree in isolated mode."""
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
CODE = r'''
from pathlib import Path
import json
import subprocess
import sys

import microtools_free
from microtools_free.batchcontract import schema

source = Path(sys.argv[1]).resolve()
installed = Path(microtools_free.__file__).resolve()
assert not installed.is_relative_to(source), installed
assert microtools_free.__version__ == "0.2.0"
for kind in ("input", "result", "error"):
    assert schema(kind)["type"] == "object"

def save(name, text):
    Path(name).write_text(text, encoding="utf-8")
    return name

prompt = save("prompt.txt", "Fictional text\n")
config = save("config.json", '{"example":true}\n')
rows = save("rows.jsonl", '{"id":"example"}\n')
log = save("log.txt", "Ordinary fictional log\n")
stream = save("stream.sse", 'data: {"id":"example","object":"chat.completion.chunk",'
              '"choices":[{"index":0,"finish_reason":"stop"}],'
              '"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}\n\n'
              'data: [DONE]\n\n')
retry = save("retry.jsonl", '{"operation_id":"example","attempt":1,'
             '"started_at":"2026-10-17T00:00:00Z","response_at":"2026-10-17T00:00:01Z",'
             '"status_code":200}\n')
batch = save("batch.jsonl", '{"custom_id":"example","method":"POST",'
             '"url":"/v1/responses","body":{}}\n')
commands = [
    ["promptdiff", prompt, prompt], ["configdiff", config, config],
    ["jsonldoctor", rows], ["logredact", log], ["streamusageaudit", stream],
    ["retrylens", retry], ["batchcontractcheck", batch],
]
for args in commands:
    result = subprocess.run([sys.executable, "-I", "-m", "microtools_free", *args],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, (args, result.returncode, result.stderr)
    assert isinstance(json.loads(result.stdout), dict), args
print("PASS: isolated installed-package execution of all seven commands and all three bundled schemas.")
'''


def main():
    with TemporaryDirectory(prefix="microtools-install-") as directory:
        subprocess.run([sys.executable, "-I", "-c", CODE, str(ROOT)], cwd=directory, check=True)
        console = shutil.which("microtools-free")
        if console is None:
            raise RuntimeError("Installed microtools-free console command was not found")
        result = subprocess.run([console, "--version"], cwd=directory,
                                text=True, capture_output=True, check=True)
        if result.stdout.strip() != "0.2.0":
            raise AssertionError(result.stdout)
        print("PASS: installed console entry point.")


if __name__ == "__main__":
    main()
