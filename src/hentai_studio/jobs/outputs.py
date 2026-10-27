"""Bounded reads of trainer output, independent of command execution."""

import csv
import io
import json
import math
import os
from pathlib import Path

from ..errors import StudioError
from ..models import Artifact, Artifacts, LogPage, Metrics
from .files import confined


class OutputReader:
    def __init__(self, job_directory, get_job):
        self.job_directory = job_directory
        self.get_job = get_job

    def logs(self, job_id, offset=0, limit=65536, tail=False):
        path = self.job_directory(job_id) / "console.log"
        if not path.exists():
            return LogPage(text="", next_offset=0, size=0)
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit) if tail else min(offset, size))
            content = stream.read(limit)
            next_offset = stream.tell()
        return LogPage(
            text=content.decode("utf-8", errors="replace"),
            next_offset=next_offset,
            size=size,
        )

    def output_root(self, job_id):
        directory = self.job_directory(job_id).resolve()
        root = directory / "output"
        if root.is_symlink() or not root.resolve().is_relative_to(directory):
            raise StudioError(
                409,
                "invalid_output_root",
                "Job output directory must remain inside its job directory.",
            )
        return root

    def output_file(self, job_id, path):
        try:
            target = confined(self.output_root(job_id), path)
        except (ValueError, OSError):
            raise StudioError(
                404,
                "artifact_not_found",
                "File does not exist inside this job's output directory.",
            ) from None
        if not target.is_file():
            raise StudioError(404, "artifact_not_found", "Artifact does not exist.")
        return target

    def metrics(self, job_id):
        job = self.get_job(job_id)
        try:
            path = self.output_file(job_id, job.project.metrics_file)
        except StudioError:
            return Metrics(items=[], truncated=False)
        limit = 1024 * 1024
        with path.open("rb") as stream:
            header = stream.readline(65536) if path.suffix == ".csv" else b""
            stream.seek(0, 2)
            size = stream.tell()
            truncated = size > limit
            stream.seek(max(len(header), size - limit) if truncated else len(header))
            if truncated:
                stream.readline(limit)  # Drop partial first row.
            data = stream.read(limit)
        # Ignore a row still being written by the trainer.
        if not data.endswith(b"\n"):
            data = data.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in data else b""
        text = data.decode("utf-8", errors="replace")
        rows = (
            csv.DictReader(
                io.StringIO(header.decode("utf-8-sig", errors="replace") + text)
            )
            if header
            else text.splitlines()
        )
        items = []
        rows = iter(rows)
        while True:
            try:
                row = next(rows)
            except StopIteration:
                break
            except csv.Error:
                break
            try:
                record = json.loads(row) if isinstance(row, str) else row
                if not isinstance(record, dict):
                    continue
                numeric = {}
                for key, value in record.items():
                    try:
                        number = float(value)
                    except (ValueError, TypeError):
                        continue
                    if math.isfinite(number):
                        numeric[str(key)] = number
                if numeric:
                    items.append(numeric)
            except (ValueError, TypeError, RecursionError):
                continue
        return Metrics(items=items[-1000:], truncated=truncated or len(items) > 1000)

    def artifacts(self, job_id):
        root = self.output_root(job_id)
        items = []
        visited = 0
        # Do not traverse directory links or return file links outside the output root.
        for directory, directories, files in os.walk(root, followlinks=False):
            visited += 1
            if visited > 2000:
                return Artifacts(items=items, truncated=True)
            directories[:] = sorted(
                name
                for name in directories
                if not (Path(directory) / name).is_symlink()
                and (Path(directory) / name).resolve().is_relative_to(root.resolve())
            )
            for name in sorted(files):
                visited += 1
                if visited > 2000:
                    return Artifacts(items=items, truncated=True)
                path = Path(directory) / name
                try:
                    target = confined(root, path.relative_to(root))
                    items.append(
                        Artifact(
                            path=path.relative_to(root).as_posix(),
                            size=target.stat().st_size,
                        )
                    )
                except (ValueError, OSError):
                    continue
        return Artifacts(items=items, truncated=False)
