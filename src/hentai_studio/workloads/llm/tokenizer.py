from __future__ import annotations

import hashlib
from pathlib import Path

from .config import DatasetConfig, TokenizerConfig
from .dataset import jsonl_files, text_from_record


def train_bpe(dataset: DatasetConfig, settings: TokenizerConfig, output: str | Path) -> Path:
    """Train and save a run-local BPE tokenizer. This deliberately reads text data."""
    if settings.mode != "train_bpe":
        raise ValueError("BPE training requires tokenizer.mode train_bpe")
    try:
        from tokenizers import Tokenizer, decoders, models, normalizers, pre_tokenizers, trainers
    except ImportError as error:
        raise RuntimeError("LLM tokenizer backend is unavailable; install the optional LLM dependencies") from error

    def documents():
        import json
        for file in jsonl_files(dataset.root):
            with file.open(encoding="utf-8") as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    try:
                        text = text_from_record(json.loads(raw), dataset.schema)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    if text.strip():
                        yield text

    tokenizer = Tokenizer(models.BPE(unk_token="<unk>"))
    tokenizer.normalizer = normalizers.Sequence([normalizers.NFKC()])
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(vocab_size=settings.vocab_size, min_frequency=settings.min_frequency, special_tokens=["<pad>", "<unk>", "<bos>", "<eos>"])
    tokenizer.train_from_iterator(documents(), trainer=trainer)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "tokenizer.json"
    tokenizer.save(str(path))
    (destination / "tokenizer.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n", encoding="utf-8")
    return path
