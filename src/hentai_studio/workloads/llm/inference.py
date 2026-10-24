"""CPU-only local inference for completed LoRA checkpoints."""

from __future__ import annotations

import gc
from pathlib import Path
from threading import Lock
from typing import Any


def _has_repeated_token_pattern(generated: Any, repetitions: int = 8, max_pattern_length: int = 4) -> bool:
    """Detect a degenerate trailing token loop without loading a model."""
    import torch

    for pattern_length in range(1, max_pattern_length + 1):
        window_length = pattern_length * repetitions
        if len(generated) < window_length:
            continue
        pattern = generated[-pattern_length:]
        if bool(torch.equal(generated[-window_length:], pattern.repeat(repetitions))):
            return True
    return False


class LocalLLMChat:
    """Lazily load one selected adapter on the CPU and generate a reply.

    This module deliberately imports Torch/Transformers only on first use.  GPU
    visibility is never consulted: both the base model and PEFT adapter are
    placed on CPU before generation.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._loaded_key: tuple[Path, Path] | None = None
        self._tokenizer: Any = None
        self._model: Any = None

    def reply(self, *, base_model: Path, adapter: Path, messages: list[dict[str, str]], max_new_tokens: int = 128) -> str:
        if not messages:
            raise ValueError("at least one chat message is required")
        if len(messages) > 48:
            raise ValueError("chat history is too long")
        if any(item.get("role") not in {"user", "assistant", "system"} or not isinstance(item.get("content"), str) for item in messages):
            raise ValueError("messages must contain role and text content")
        if not 1 <= max_new_tokens <= 256:
            raise ValueError("max_new_tokens must be between 1 and 256")
        if not (adapter / "adapter_config.json").is_file():
            raise ValueError("the selected checkpoint does not contain a complete LoRA adapter")

        with self._lock:
            self._ensure_loaded(base_model, adapter)
            import torch
            from transformers import StoppingCriteria, StoppingCriteriaList

            class RepeatedTokenPattern(StoppingCriteria):
                """Stop degenerate one-to-four-token loops before they reach the UI."""

                def __init__(self, prompt_length: int, repetitions: int = 8) -> None:
                    self.prompt_length, self.repetitions = prompt_length, repetitions

                def __call__(self, input_ids, scores, **kwargs) -> bool:
                    generated = input_ids[0, self.prompt_length:]
                    return _has_repeated_token_pattern(generated, self.repetitions)

            prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=3072)
            inputs = {name: value.to("cpu") for name, value in inputs.items()}
            eos_token_ids = [self._tokenizer.eos_token_id]
            im_end = self._tokenizer.convert_tokens_to_ids("<|im_end|>")
            if isinstance(im_end, int) and im_end >= 0 and im_end not in eos_token_ids:
                eos_token_ids.append(im_end)
            with torch.inference_mode():
                output = self._model.generate(
                    **inputs,
                    do_sample=True,
                    temperature=0.70,
                    top_p=0.90,
                    repetition_penalty=1.12,
                    no_repeat_ngram_size=4,
                    max_new_tokens=max_new_tokens,
                    eos_token_id=eos_token_ids,
                    pad_token_id=self._tokenizer.eos_token_id,
                    stopping_criteria=StoppingCriteriaList([RepeatedTokenPattern(inputs["input_ids"].shape[-1])]),
                    use_cache=True,
                )
            generated = output[0][inputs["input_ids"].shape[-1]:]
            return self._tokenizer.decode(generated, skip_special_tokens=True).strip()

    def _ensure_loaded(self, base_model: Path, adapter: Path) -> None:
        key = (base_model.resolve(), adapter.resolve())
        if self._loaded_key == key:
            return
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(base_model), local_files_only=True)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            str(base_model), local_files_only=True, dtype=torch.bfloat16, device_map="cpu"
        )
        model = PeftModel.from_pretrained(base, str(adapter), local_files_only=True).to("cpu").eval()
        self._tokenizer, self._model, self._loaded_key = tokenizer, model, key

    def unload(self) -> None:
        """Release the heavyweight CPU model after a concurrent training probe."""
        with self._lock:
            self._model = None
            self._tokenizer = None
            self._loaded_key = None
            gc.collect()
