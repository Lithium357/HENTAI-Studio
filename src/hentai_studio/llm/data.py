"""Local dataset and prompt formatting, usable from the external trainer environment."""

import json
from pathlib import Path


def format_messages(tokenizer, messages, *, generation=False):
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array.")
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"system", "user", "assistant"}
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError(
                "Each message needs a system/user/assistant role and string content."
            )
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=generation
        )
    # Scratch tokenizers need not have an HF chat template. Keep train/test identical.
    return "".join(f"{m['role']}: {m['content']}\n" for m in messages) + (
        "assistant: " if generation else ""
    )


def read_records(path):
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or not (
                    isinstance(record.get("text"), str)
                    or isinstance(record.get("messages"), list)
                ):
                    raise TypeError("Expected a text string or messages array.")
                yield record
            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"Invalid dataset record on line {number}: {error}"
                ) from error


def encode_record(tokenizer, record, max_length):
    text = record.get("text")
    if text is None:
        text = format_messages(tokenizer, record["messages"])
    is_chat_template = record.get("text") is None and bool(
        getattr(tokenizer, "chat_template", None)
    )
    encoded = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        add_special_tokens=not is_chat_template,
    )
    eos = tokenizer.eos_token_id
    if (
        eos is not None
        and len(encoded["input_ids"]) < max_length
        and (not encoded["input_ids"] or encoded["input_ids"][-1] != eos)
    ):
        encoded["input_ids"].append(eos)
        if "attention_mask" in encoded:
            encoded["attention_mask"].append(1)
        if "token_type_ids" in encoded:
            encoded["token_type_ids"].append(0)
    if len(encoded["input_ids"]) < 2:
        raise ValueError("Each dataset example must contain at least two tokens.")
    return encoded
