"""Local inference worker. JSONL on stdin/stdout; model diagnostics go to stderr."""

import contextlib
import json
import sys
from pathlib import Path

if __package__:
    from .data import format_messages
else:
    from data import format_messages


def main():
    config = json.loads(sys.stdin.readline())
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        directory = Path(config["checkpoint"])
        tokenizer = AutoTokenizer.from_pretrained(
            config["tokenizer"] or directory,
            local_files_only=True,
            trust_remote_code=False,
        )
        model = AutoModelForCausalLM.from_pretrained(
            directory,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.float32,
        )
        model.to(config["device"])
        model.eval()
        model.config.use_cache = True
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
                prompt = format_messages(
                    tokenizer, request["messages"], generation=True
                )
                inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
                context_size = getattr(
                    model.config,
                    "max_position_embeddings",
                    getattr(model.config, "n_positions", None),
                )
                if (
                    context_size
                    and inputs["input_ids"].shape[1] + request["max_tokens"]
                    > context_size
                ):
                    raise ValueError(
                        "Conversation plus requested response exceeds this model's context window. Clear the chat or lower max tokens."
                    )
                result = model.generate(
                    **inputs,
                    max_new_tokens=request["max_tokens"],
                    do_sample=request["temperature"] > 0,
                    **(
                        {"temperature": request["temperature"]}
                        if request["temperature"] > 0
                        else {}
                    ),
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
                generated = result[0, inputs["input_ids"].shape[1] :]
                text = tokenizer.decode(generated, skip_special_tokens=True)
            print(json.dumps({"content": text, "tokens": len(generated)}), flush=True)
        except Exception as error:  # noqa: BLE001 - isolate arbitrary model failures at the worker protocol boundary
            print(json.dumps({"error": str(error)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - isolate arbitrary model failures at the worker protocol boundary
        print(json.dumps({"error": str(error)}), flush=True)
        sys.exit(1)
