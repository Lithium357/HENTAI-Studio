"""Exclusive dashboard ownership without tying trainer lifetime to the dashboard."""

import os
from pathlib import Path


class WorkspaceLease:
    def __init__(self, root: Path):
        self.path = root / "workspace.lock"
        self.stream = None

    def acquire(self):
        if self.stream is not None:
            raise RuntimeError("Workspace lease is already acquired.")
        stream = self.path.open("a+b")
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise RuntimeError(
                "This workspace is already served by another Studio process."
            ) from None
        self.stream = stream

    def close(self):
        if self.stream:
            if os.name == "nt":
                import msvcrt

                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None
