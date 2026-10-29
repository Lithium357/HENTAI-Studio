"""Optional standalone scratch trainer. Executed in the project's chosen Python environment."""

import argparse
import json
import math
import os
from pathlib import Path

if __package__:
    from .data import encode_record, read_records
else:
    from data import encode_record, read_records


def train(config):
    try:
        import torch
        from transformers import (
            AutoConfig,
            AutoModelForCausalLM,
            AutoTokenizer,
            Trainer,
            TrainerCallback,
            TrainingArguments,
            set_seed,
        )
    except ImportError as error:
        raise RuntimeError(
            "Install torch, transformers>=4.46,<5 and accelerate in the selected training Python environment. Studio itself does not load these packages."
        ) from error

    output = Path(os.environ["STUDIO_OUTPUT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "training-config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    set_seed(config["seed"])
    tokenizer = AutoTokenizer.from_pretrained(
        config["tokenizer"], local_files_only=True, trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValueError("The tokenizer needs a padding or EOS token.")
        tokenizer.pad_token = tokenizer.eos_token
    model_config = AutoConfig.from_pretrained(
        config["model"], local_files_only=True, trust_remote_code=False
    )
    # No pretrained weight loading: this is scratch initialization.
    model_config.vocab_size = len(tokenizer)
    model_config.bos_token_id = tokenizer.bos_token_id
    model_config.eos_token_id = tokenizer.eos_token_id
    model_config.pad_token_id = tokenizer.pad_token_id
    model = AutoModelForCausalLM.from_config(model_config, trust_remote_code=False)
    model.config.pad_token_id = tokenizer.pad_token_id
    if config["gradient_checkpointing"]:
        model.config.use_cache = False
    print(
        f"Scratch model initialized: {sum(p.numel() for p in model.parameters()):,} parameters",
        flush=True,
    )

    class Records(torch.utils.data.Dataset):
        def __init__(self, path):
            # An offset index avoids loading the dataset or its tokenization into RAM.
            self.path = path
            self.offsets = []
            with Path(path).open("rb") as handle:
                while True:
                    offset = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    if line.strip():
                        self.offsets.append(offset)
            if not self.offsets:
                raise ValueError("Dataset contains no examples.")

        def __len__(self):
            return len(self.offsets)

        def __getitem__(self, index):
            with Path(self.path).open("rb") as handle:
                handle.seek(self.offsets[index])
                record = json.loads(handle.readline().decode("utf-8"))
            return encode_record(tokenizer, record, config["max_length"])

    # Validate record shapes before allocating optimizer state.
    count = sum(
        1
        for record in read_records(config["dataset"])
        if encode_record(tokenizer, record, config["max_length"])
    )
    print(
        f"Dataset ready: {count:,} examples. Loss covers all non-padding tokens.",
        flush=True,
    )

    def collate(features):
        batch = tokenizer.pad(features, return_tensors="pt")
        labels = batch["input_ids"].clone()
        labels[batch["attention_mask"] == 0] = -100
        batch["labels"] = labels
        return batch

    class Metrics(TrainerCallback):
        def on_save(self, args, state, control, **kwargs):
            tokenizer.save_pretrained(output / f"checkpoint-{state.global_step}")

        def on_log(self, args, state, control, logs=None, **kwargs):
            values = {
                key: value
                for key, value in (logs or {}).items()
                if isinstance(value, (int, float)) and math.isfinite(value)
            }
            if values:
                with (output / "metrics.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps({**values, "step": state.global_step}) + "\n"
                    )

    arguments = TrainingArguments(
        output_dir=str(output),
        per_device_train_batch_size=config["batch_size"],
        gradient_accumulation_steps=config["gradient_accumulation"],
        learning_rate=config["learning_rate"],
        num_train_epochs=config["epochs"],
        max_steps=config["max_steps"],
        save_steps=config["save_steps"],
        save_total_limit=3,
        logging_steps=1,
        report_to=[],
        disable_tqdm=True,
        seed=config["seed"],
        bf16=config["precision"] == "bf16",
        fp16=config["precision"] == "fp16",
        gradient_checkpointing=config["gradient_checkpointing"],
        optim="adamw_torch",
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=Records(config["dataset"]),
        data_collator=collate,
        callbacks=[Metrics()],
    )
    resume = os.environ.get("STUDIO_RESUME_DIR")
    checkpoint = None
    if resume:
        candidates = [
            p
            for p in Path(resume).glob("checkpoint-*")
            if p.is_dir()
            and p.name[11:].isdigit()
            and (p / "trainer_state.json").is_file()
        ]
        if not candidates:
            raise ValueError(
                "Resume source has no complete Trainer checkpoint. Start a new job or choose a job with checkpoint-* output."
            )
        checkpoint = str(max(candidates, key=lambda p: int(p.name[11:])))
    if checkpoint:
        print(f"Resuming optimizer and model state from {checkpoint}", flush=True)
    trainer.train(resume_from_checkpoint=checkpoint)
    trainer.save_model(str(output / "model"))
    tokenizer.save_pretrained(output / "model")
    # Include the tokenizer in intermediate checkpoints too, for direct local chat loading.
    for directory in output.glob("checkpoint-*"):
        if directory.is_dir():
            tokenizer.save_pretrained(directory)
    print(f"Saved local model and tokenizer to {output / 'model'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-json", required=True)
    train(json.loads(parser.parse_args().config_json))
