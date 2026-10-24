# Contributing

HENTAI is a proprietary personal research project, not an open-source project. Contributions are accepted only with the repository owner's prior approval. See [source provenance](SOURCE_PROVENANCE.md) and [LICENSE.HENTAI](LICENSE.HENTAI).

## Before proposing a change

- Open or discuss one focused problem before doing extensive work.
- Do not submit dataset media, manifests containing private paths, model weights, checkpoints, logs, generated samples, credentials, or machine secrets.
- Keep metadata-only tools media-blind.
- Do not interrupt an active training run to test an unrelated UI or documentation change.
- Create a new run/configuration when tensor shapes, vocabulary identity, optimizer layout, or training objectives change.

## Local verification

```bash
source .venv/bin/activate
python -m pytest -q
git diff --check
```

Diffusion model changes belong in HENTAI. For model-construction changes there:

```bash
scratchtag smoke --config configs/rx7800xt-scratch-v3-x4-512.json
```

Run `scripts/architecture_probe.py` only when the training GPU is idle. It performs a real synthetic optimizer update and competes for VRAM.

## Change expectations

- Add focused tests for behavior and compatibility boundaries.
- Preserve checkpoint recovery unless the change explicitly versions the format.
- Keep the training objective and inference scheduler prediction type aligned.
- Keep historical generation tied to each run's copied config and vocabulary.
- Update relevant documentation in the same commit.
- State whether a command touches media, requires a GPU, or mutates run state.
- Avoid adding heavyweight imports to dashboard-only startup.

## Documentation style

Documentation must distinguish:

- Native neural resolution from resized export dimensions
- Optimizer steps from micro-batches and images seen
- A completed checkpoint from a finalized/promoted model
- Rolling operational estimates from controlled evaluation metrics
- Tested configurations from merely plausible configurations

## Rights

By submitting a contribution, you represent that you have the right to submit it and agree that, if accepted, it may be incorporated and distributed under this repository's proprietary license. No ownership transfer or additional license is implied without a separate written agreement.
