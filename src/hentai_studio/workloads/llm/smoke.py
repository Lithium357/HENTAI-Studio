from __future__ import annotations

from dataclasses import asdict

from .config import LLMConfig


def smoke_test(config: LLMConfig, *, device: str = "cpu", tiny: bool = False) -> dict[str, object]:
    """One synthetic causal-LM update. It never reads dataset text or model weights."""
    try:
        import torch
        from safetensors.torch import load_file, save_file
        from transformers import LlamaConfig, LlamaForCausalLM
    except ImportError as error:
        raise RuntimeError("LLM training backend is unavailable; install optional LLM dependencies") from error

    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("requested accelerator is unavailable")
    hidden = 64 if tiny else config.model.hidden_size
    heads = 4 if tiny else config.model.num_attention_heads
    kv_heads = 2 if tiny else config.model.num_key_value_heads
    layers = 2 if tiny else config.model.num_hidden_layers
    context = min(32 if tiny else config.dataset.context_length, config.model.max_position_embeddings)
    intermediate = 128 if tiny else config.model.intermediate_size
    vocab = 256 if tiny else config.tokenizer.vocab_size
    model_config = LlamaConfig(
        vocab_size=vocab,
        hidden_size=hidden,
        intermediate_size=intermediate,
        num_hidden_layers=layers,
        num_attention_heads=heads,
        num_key_value_heads=kv_heads,
        max_position_embeddings=config.model.max_position_embeddings,
        pad_token_id=0,
        bos_token_id=2,
        eos_token_id=3,
        use_cache=False,
    )
    model = LlamaForCausalLM(model_config).to(device)
    if config.training.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.training.learning_rate)
    tokens = torch.randint(4, vocab, (1, context), device=device)
    outputs = model(input_ids=tokens, labels=tokens, use_cache=False)
    outputs.loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    probe_path = config.output / ".smoke-model.safetensors"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    save_file({key: value.detach().cpu().contiguous() for key, value in model.state_dict().items()}, str(probe_path))
    loaded = load_file(str(probe_path))
    probe_path.unlink(missing_ok=True)
    return {"ok": True, "device": device, "loss": float(outputs.loss.detach().cpu()), "parameters": sum(item.numel() for item in model.parameters()), "savedTensors": len(loaded), "architecture": asdict(config.model)}
