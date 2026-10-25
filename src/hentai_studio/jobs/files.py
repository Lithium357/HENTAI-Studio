import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = {"starting", "running", "stopping"}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers and virus scanners can briefly hold a handle that blocks
        # replacement. Keep the fully written temporary file and retry atomically.
        for attempt in range(50):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)
    finally:
        Path(temporary).unlink(missing_ok=True)


def confined(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Path must identify a file inside the job output directory.")
    return target
