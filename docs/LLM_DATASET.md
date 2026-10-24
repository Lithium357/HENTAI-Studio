# LLM dataset contract

The general scratch workload accepts JSON Lines text. The ERP LoRA workload additionally reads local CSV archives with a `message` column. Audit and tokenizer creation read text only; they never inspect existing image or GIF media.

Set `dataset.schema` explicitly. The loader does not guess when fields overlap.

```json
{"text":"A complete training document."}
```

```json
{"prompt":"Question", "completion":"Answer"}
```

```json
{"messages":[{"role":"user","content":"Hello"},{"role":"assistant","content":"Hi"}]}
```

Message roles are limited to `system`, `user`, and `assistant`. Blank, malformed, and schema-invalid rows are counted by `hentai-studio llm-audit`; training ignores them. The audit reports files, records, valid rows, invalid rows, empty rows, characters, and duplicate text hashes.

Train/validation membership is deterministic: a stable hash of the record text and configured seed selects the split. Dataset fingerprints include supported local JSONL and CSV file paths, sizes, modification times, schema, context length, packing mode, and tokenizer identity. The prepared run records its source-file count alongside that fingerprint.

The scratch trainer concatenates encoded documents with EOS and emits fixed context-length causal blocks in memory. The LoRA/CPT path uses a versioned packed-token cache with separate deterministic train/validation streams. Its manifest binds the cache to the corpus fingerprint, tokenizer identity, context length, split seed, and validation fraction; an incompatible or incomplete cache is rejected before model loading.
