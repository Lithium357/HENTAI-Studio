"""Find complete saved weights without importing ML packages or loading tensors."""

import json
import re
import struct
import zipfile

from ..errors import StudioError
from ..models_base import Model


class CheckpointSelection(Model):
    project_id: str
    job_id: str
    checkpoint: str
    step: int | None
    job_created_at: str


def _json(path, limit=16 * 1024 * 1024):
    if path.stat().st_size > limit:
        raise ValueError("Metadata too large")
    return json.loads(path.read_text(encoding="utf-8"))


def _weight(path, root):
    if (
        not path.resolve().is_relative_to(root)
        or not path.is_file()
        or path.stat().st_size == 0
    ):
        return False
    if path.suffix == ".safetensors":
        with path.open("rb") as handle:
            length = struct.unpack("<Q", handle.read(8))[0]
            if not 0 < length <= 16 * 1024 * 1024:
                return False
            header = json.loads(handle.read(length))
        offsets = [
            item["data_offsets"]
            for key, item in header.items()
            if key != "__metadata__"
        ]
        return bool(offsets) and all(
            len(pair) == 2
            and all(isinstance(n, int) and n >= 0 for n in pair)
            and pair[0] <= pair[1]
            and 8 + length + pair[1] <= path.stat().st_size
            for pair in offsets
        )
    # Modern torch saves are ZIP archives; the central directory is written last.
    # Legacy pickle saves cannot be inspected safely without loading, so leave final validation to inference.
    with path.open("rb") as handle:
        zipped = handle.read(2) == b"PK"
    if zipped:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.infolist())
    return True


def complete_weights(directory, output):
    try:
        root = output.resolve()
        if not directory.resolve().is_relative_to(root):
            return False
        config = directory / "config.json"
        if not config.resolve().is_relative_to(root) or not isinstance(
            _json(config), dict
        ):
            return False
        for name in ("model.safetensors", "pytorch_model.bin"):
            if (directory / name).exists() and _weight(directory / name, root):
                return True
        for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
            index = directory / name
            if not index.is_file() or not index.resolve().is_relative_to(root):
                continue
            mapping = _json(index).get("weight_map")
            if (
                isinstance(mapping, dict)
                and mapping
                and all(
                    isinstance(shard, str) and _weight(directory / shard, root)
                    for shard in set(mapping.values())
                )
            ):
                return True
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        struct.error,
        zipfile.BadZipFile,
    ):
        pass
    return False


def latest_checkpoint(workspace, project_id, job_id=None):
    project = workspace.get_project(project_id)
    if project.llm is None:
        raise StudioError(
            409,
            "not_llm_project",
            "Configure this project as a scratch LLM project first.",
        )
    if job_id:
        job = workspace.get_job(job_id)
        if job.project_id != project.id:
            raise StudioError(422, "wrong_project", "Choose a run from this project.")
        jobs = [job]
    else:
        jobs = sorted(
            workspace.list_jobs(project.id),
            key=lambda job: (job.created_at, job.id),
            reverse=True,
        )
    for job in jobs:
        output = workspace.job_directory(job.id) / "output"
        if job.state == "succeeded" and complete_weights(output / "model", output):
            return CheckpointSelection(
                project_id=project.id,
                job_id=job.id,
                checkpoint="model",
                step=None,
                job_created_at=job.created_at,
            )
        try:
            directories = [
                (int(match[1]), path)
                for path in output.iterdir()
                if (match := re.fullmatch(r"checkpoint-(\d+)", path.name))
                and path.is_dir()
            ]
        except OSError:
            continue
        for step, directory in sorted(
            directories, key=lambda item: item[0], reverse=True
        ):
            if workspace._busy(job):
                try:
                    state = _json(directory / "trainer_state.json")
                    if state.get("global_step") != step:
                        continue
                except (OSError, ValueError, AttributeError):
                    continue
            if complete_weights(directory, output):
                return CheckpointSelection(
                    project_id=project.id,
                    job_id=job.id,
                    checkpoint=directory.name,
                    step=step,
                    job_created_at=job.created_at,
                )
    raise StudioError(
        404,
        "checkpoint_not_found",
        "No complete saved checkpoint is available yet. Wait for a checkpoint save or select a model directory manually.",
    )
