# Command line

```text
hentai-studio serve [--workspace PATH] [--host 127.0.0.1] [--port 7860]
```

The workspace defaults to `~/.hentai-studio` and is created when absent. It contains registrations and durable job state. No project or training config is required to launch. Use the dashboard or typed API to register projects. Startup rejects a workspace already served by another process. Closing the server leaves supervisors running; restart against the same workspace to reconnect.

The old `dashboard --project --config` and `studio --project --storage-root` interfaces have been removed. Model-specific project paths and storage layouts are not part of the application contract.

## Optional causal-LM utilities

Install `pip install '.[llm]'` to use the bundled standalone training utilities. They are separate from project management:

- `llm-audit --config FILE`
- `llm-validate --config FILE`
- `llm-prepare --config FILE --run-id ID [--display-name NAME]`
- `llm-tokenizer --config FILE --output DIRECTORY`
- `llm-build-packed-cache --config FILE [--output DIRECTORY] [--overwrite]`
- `llm-smoke --config FILE [--device cpu|cuda] [--tiny]`
- `llm-train --config FILE [--no-resume] [--device cpu|cuda]`
- `llm-checkpoint-verify --run-dir DIRECTORY --step NUMBER`
- `llm-normalize-erp --source PATH --output DIRECTORY [--limit-files NUMBER]`

Use `hentai-studio COMMAND --help` for arguments. These utilities retain their own config and storage semantics; the generic dashboard does not infer them. See LLM_TRAINING.md for details.
