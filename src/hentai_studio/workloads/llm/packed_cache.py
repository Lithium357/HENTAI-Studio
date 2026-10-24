"""Versioned fixed-block token cache for deterministic local LoRA CPT."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .dataset import fingerprint, source_files
from .lora_cpt import ArchiveBlocks

CACHE_SCHEMA_VERSION = 1

@dataclass(frozen=True, slots=True)
class PackedCacheManifest:
    schema_version: int
    complete: bool
    corpus_fingerprint: str
    tokenizer_identity: str
    context_length: int
    seed: int
    validation_fraction: float
    train_blocks: int
    validation_blocks: int
    token_dtype: str = "uint32-le"

def _manifest_path(root: Path) -> Path:
    return root / "manifest.json"

def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)

def expected_manifest(config, tokenizer_identity: str) -> PackedCacheManifest:
    return PackedCacheManifest(CACHE_SCHEMA_VERSION, True, fingerprint(source_files(config.dataset.root), config.dataset, tokenizer_identity), tokenizer_identity, config.dataset.context_length, config.seed, config.dataset.validation_fraction, 0, 0)

def load_manifest(root: str | Path, config, tokenizer_identity: str) -> PackedCacheManifest:
    path = _manifest_path(Path(root))
    if not path.is_file():
        raise ValueError(f"packed cache is missing manifest: {path}")
    manifest = PackedCacheManifest(**json.loads(path.read_text(encoding="utf-8")))
    expected = expected_manifest(config, tokenizer_identity)
    for key in ("schema_version", "complete", "corpus_fingerprint", "tokenizer_identity", "context_length", "seed", "validation_fraction", "token_dtype"):
        if getattr(manifest, key) != getattr(expected, key):
            raise ValueError(f"packed cache manifest mismatch for {key}; rebuild the cache")
    for name in ("train", "validation"):
        path = Path(root) / f"{name}.u32"; blocks = getattr(manifest, f"{name}_blocks")
        if blocks <= 0 or not path.is_file() or path.stat().st_size != blocks * manifest.context_length * 4:
            raise ValueError(f"packed cache {name} stream is incomplete or corrupt")
    return manifest

def _permutation_parameters(blocks: int, seed: int) -> tuple[int, int]:
    """Return a deterministic affine permutation over [0, blocks)."""
    if blocks <= 1: return 1, 0
    raw = hashlib.blake2b(f"packed-block-order:{seed}:{blocks}".encode(), digest_size=16).digest()
    multiplier = (int.from_bytes(raw[:8], "big") | 1) % blocks or 1
    while math.gcd(multiplier, blocks) != 1: multiplier = (multiplier + 2) % blocks or 1
    return multiplier, int.from_bytes(raw[8:], "big") % blocks

class PackedBlocks:
    def __init__(self, root: str | Path, stream: str, context_length: int, blocks: int, start: int = 0, limit: int | None = None, shuffle_seed: int | None = None):
        if stream not in {"train", "validation"}: raise ValueError("stream must be train or validation")
        if not 0 <= start <= blocks: raise ValueError("packed block offset is outside the cached stream")
        self.path = Path(root) / f"{stream}.u32"; self.context_length, self.blocks, self.start, self.limit = context_length, blocks, start, limit
        self.permutation = _permutation_parameters(blocks, shuffle_seed) if shuffle_seed is not None else None

    def __iter__(self) -> Iterator[list[int]]:
        total = self.blocks if self.limit is None else min(self.blocks, self.start + self.limit)
        with self.path.open("rb") as handle:
            for logical_index in range(self.start, total):
                index = logical_index if self.permutation is None else (self.permutation[0] * logical_index + self.permutation[1]) % self.blocks
                handle.seek(index * self.context_length * 4)
                raw = handle.read(self.context_length * 4)
                if len(raw) != self.context_length * 4: raise RuntimeError("packed cache ended before verified block count")
                yield list(struct.unpack(f"<{self.context_length}I", raw))

def _write_stream(destination: Path, blocks: Iterator[list[int]], context_length: int) -> int:
    count = 0
    with destination.open("wb") as handle:
        for block in blocks:
            if len(block) != context_length: raise RuntimeError("archive yielded unexpected packed block length")
            handle.write(struct.pack(f"<{context_length}I", *block)); count += 1
    return count

def build_packed_cache(config, tokenizer, root: str | Path, *, overwrite: bool = False) -> PackedCacheManifest:
    """Build atomically: incomplete caches are never consumed by training."""
    cache = Path(root).resolve(); tokenizer_identity = str(config.tokenizer.base_model or config.model.base_model or "unknown")
    if cache.exists() and not overwrite:
        try: return load_manifest(cache, config, tokenizer_identity)
        except ValueError: raise ValueError(f"cache destination already exists but is incompatible: {cache}")
    staging = cache.with_name(cache.name + ".building")
    if staging.exists(): raise ValueError(f"cache build already exists or needs inspection: {staging}")
    staging.mkdir(parents=True)
    try:
        source = Path(config.dataset.root); size = config.dataset.context_length
        train_count = _write_stream(staging / "train.u32", iter(ArchiveBlocks(source, tokenizer, size, config.seed, config.dataset.validation_fraction, False)), size)
        validation_count = _write_stream(staging / "validation.u32", iter(ArchiveBlocks(source, tokenizer, size, config.seed, config.dataset.validation_fraction, True)), size)
        base = expected_manifest(config, tokenizer_identity)
        manifest = PackedCacheManifest(**{**asdict(base), "train_blocks": train_count, "validation_blocks": validation_count})
        _atomic_json(staging / "manifest.json", asdict(manifest))
        if cache.exists(): shutil.rmtree(cache)
        os.replace(staging, cache)
        return manifest
    except Exception:
        raise
