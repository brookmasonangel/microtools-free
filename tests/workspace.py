"""Disposable, project-local test directories with checked cleanup boundaries."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid


@contextmanager
def temp_workspace():
    project = Path(__file__).resolve().parent.parent
    base = project / ".test-work"
    base.mkdir(exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        target = path.resolve()
        if target.parent != base.resolve() or not target.is_relative_to(project) or target == base.resolve():
            raise RuntimeError("Refusing test cleanup outside the project test workspace")
        shutil.rmtree(target)
