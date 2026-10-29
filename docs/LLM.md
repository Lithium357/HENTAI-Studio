# Scratch LLM training and local chat

Studio can initialize a causal language model from a **local model configuration**, train it on a **local JSONL dataset**, and test its saved checkpoints in a chat window. There are no OpenAI accounts, remote inference APIs, or pretrained weight downloads in this workflow.

The built-in runner supports Transformers-compatible causal language models and tokenizers. Custom architectures that need custom Python code should continue using an external training command; the built-in loader does not execute `trust_remote_code`. Chat tests full model checkpoints, not LoRA adapters or GGUF files.

## Prepare the training environment

Use the environment where your model will run, independently of the Studio server:

```sh
python -m venv .llm-venv
.llm-venv/bin/python -m pip install '.[llm]'
```

On Windows use `.llm-venv\Scripts\python` instead. Install the appropriate PyTorch build for your GPU separately when needed. Studio does not install or select GPU drivers, a CUDA/ROCm runtime, or device-specific PyTorch wheels.

The optional extra supplies PyTorch, Transformers 4.x, and Accelerate. Ordinary Studio installation and startup remain free of ML imports. The trainer is a separate process launched with the Python executable you select in the project form.

## Try a small model from scratch

The repository includes a small GPT-2 architecture configuration, illustrative JSONL records, and a tokenizer-training helper. Everything is local:

```sh
.llm-venv/bin/python examples/llm/train_tokenizer.py examples/llm/train.jsonl examples/llm/tokenizer
```

Register this checkout in Studio and select **Scratch LLM training**:

| Field | Example |
| --- | --- |
| Training Python executable | Absolute path to `.llm-venv/bin/python` |
| Model configuration directory | `examples/llm` |
| Tokenizer directory | `examples/llm/tokenizer` |
| Training dataset | `examples/llm/train.jsonl` |
| Sequence length | `128` for the small example |
| Batch size | `1` |
| Gradient accumulation | `1` |
| Max optimizer steps | `10` |
| Save checkpoint every N steps | `5` |
| Precision | `FP32` |

This tiny example demonstrates the workflow; a few illustrative records do not produce a useful language model. Bring your own architecture configuration, tokenizer corpus, and training dataset for real work. Model dimensions and context size must fit your hardware and configured sequence length.

In **Launch a run**, select **New run** and click **Start new run**. The profile generates the project's `train` command, records a configuration snapshot, and writes numeric training logs to `metrics.jsonl`. Jobs use Studio's existing process supervision, console, artifacts, stop, and resume controls.

The runner initializes fresh weights with `AutoModelForCausalLM.from_config`. It reads no pretrained weights. Tokenizer vocabulary size is used for the model's embedding vocabulary. Precision, batch size, gradient accumulation, learning rate, epoch/step budget, checkpoint interval, seed, and gradient checkpointing are configurable. `max_steps: -1` uses the epoch budget; positive values select an optimizer-step budget.

## Dataset format

Each nonblank line must be an independent JSON object with either `text` or `messages`:

```jsonl
{"text":"A complete example of plain training text."}
{"messages":[{"role":"user","content":"Hello"},{"role":"assistant","content":"Hello!"}]}
```

For messages, Studio uses the tokenizer's chat template if present. Otherwise both training and chat use the same `role: content` format with one message per line. Plain text is used directly. EOS is appended when available and when space remains. Examples are truncated to the configured sequence length. Training predicts all non-padding tokens, including user and system text; assistant-only masking, sequence packing, validation splits, and distributed orchestration are not currently provided. The trainer indexes line offsets instead of loading the whole dataset into memory.

## Checkpoints and resume

A successful job saves its final model and tokenizer in `output/model`. Intermediate `checkpoint-N` directories contain training state and a tokenizer. They appear with the other output artifacts.

To resume, select a finished job, expand **Launch a run**, select **Resume run**, choose `train`, and click **Resume run**. The named source receives the resume request. The runner uses the highest-numbered checkpoint containing `trainer_state.json` and restores Trainer state. Keep the model configuration, tokenizer, and dataset consistent with the original job. Increase the training budget if more steps are needed. A job stopped before its first checkpoint cannot be resumed. Stop terminates the trainer and does not request a final checkpoint.

## Test responses locally

Select a scratch LLM project and open **Chat tester**:

1. Choose **Selected job output** and use `model` for final weights, or `checkpoint-N` for an intermediate save. Alternatively, choose **Local directory** and supply a saved model directory.
2. Select **CPU** (default) or **GPU (CUDA / ROCm)** and click **Load checkpoint**. Loading is explicit and may take time. The local loader uses the project's configured tokenizer.
3. Send a prompt. Adjust the system prompt, temperature (`0` for greedy decoding), or maximum new tokens to compare responses. The full conversation is passed to the model on each turn.
4. Use **Clear chat** to reset the conversation and **Unload model** to release the inference worker's memory.

Only one chat model can be loaded in a Studio server at a time. GPU loading is blocked while a Studio job is active, and new jobs are blocked while a GPU chat model is loaded. CPU inference remains available while training, although it uses host RAM and CPU. Studio never stops a training job to make space for chat. The selected model's context window must fit the prompt plus the requested response budget.

Inference runs in a separate process, with a 120-second load/response timeout and offline model loading. Its diagnostic log is `<workspace>/chat/<project-id>.log`. Chat text is held only in browser-tab memory and is not written to the workspace. Switching projects keeps their conversations separate. Closing a browser tab does not unload a model; unload explicitly or close the Studio server. Closing the server stops only its inference workers; existing training supervisors retain their normal independent lifecycle.

The response is displayed when generation completes; token streaming is not implemented. The built-in chat UI waits for the current response before another model operation. An early scratch checkpoint may produce empty, repetitive, or incoherent text; the chat tester does not imply model quality.

## API and Python client

Register a scratch project using the optional `llm` field on `POST /api/projects` (the generated train command means `commands` may be omitted):

```json
{
  "root": "/absolute/project",
  "llm": {
    "python": "/absolute/project/.llm-venv/bin/python",
    "model": "config",
    "tokenizer": "tokenizer",
    "dataset": "train.jsonl",
    "max_steps": 1000,
    "save_steps": 100
  }
}
```

`PATCH /api/projects/{id}` can replace `llm`, or set it to `null` to return to external-command management. When removing the profile, supply the desired `commands` too. A non-null profile owns the `train` command and `metrics.jsonl` filename; additional named commands remain available. Projects with active jobs or loaded chat models cannot be edited; unload a chat model before removing its profile.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/projects/{id}/chat` | Read model load status |
| POST | `/api/projects/{id}/chat/load` | Load `{checkpoint, job_id?, device?, tokenizer?}` |
| POST | `/api/projects/{id}/chat/unload` | Release the inference worker |
| POST | `/api/projects/{id}/chat/completions` | Generate from `{messages, temperature?, max_tokens?}` |

A completion returns `{content, tokens}`. Requests allow at most 64 messages, 8,192 characters per message, and 48,000 message characters in total; responses are capped at 2,048 new tokens. Checkpoint paths selected within a job cannot escape its output directory. Loading from a local directory is deliberately supported for existing scratch-model checkpoints.

```python
from hentai_studio import StudioClient

studio = StudioClient(timeout=130)  # local model load/generation can take time
project = studio.create_llm_project(
    "/absolute/project", model="config", tokenizer="tokenizer",
    dataset="train.jsonl", python="/absolute/project/.llm-venv/bin/python",
    max_steps=1000,
)
job = studio.wait(studio.start_job(project), timeout=86400)
studio.load_chat(project, "model", job=job)  # CPU by default
reply = studio.chat(project, [{"role": "user", "content": "Hello!"}])
print(reply["content"])
studio.unload_chat(project)
```

Implementation references: [Transformers Trainer](https://huggingface.co/docs/transformers/main_classes/trainer), [model initialization from configuration](https://huggingface.co/docs/transformers/model_doc/auto#transformers.AutoModelForCausalLM.from_config), and [chat templates](https://huggingface.co/docs/transformers/chat_templating).
