"""Build a fresh byte-level tokenizer from a local JSONL dataset. No model download."""

import argparse
import json
from pathlib import Path

from tokenizers import ByteLevelBPETokenizer
from transformers import PreTrainedTokenizerFast

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dataset", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--vocab-size", type=int, default=4096)
args = parser.parse_args()


def texts():
    with args.dataset.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if "text" in record:
                yield record["text"]
            else:
                yield "".join(
                    f"{m['role']}: {m['content']}\n" for m in record["messages"]
                )


tokenizer = ByteLevelBPETokenizer()
tokenizer.train_from_iterator(
    texts(),
    vocab_size=args.vocab_size,
    min_frequency=1,
    special_tokens=["<|bos|>", "<|eos|>", "<|pad|>"],
)
args.output.mkdir(parents=True, exist_ok=True)
fast = PreTrainedTokenizerFast(
    tokenizer_object=tokenizer._tokenizer,
    bos_token="<|bos|>",
    eos_token="<|eos|>",
    pad_token="<|pad|>",
)
fast.save_pretrained(args.output)
print(f"Saved local tokenizer with {len(fast):,} tokens to {args.output}")
