# Contributing to HENTAI Studio

Studio is a standalone local project and job manager. Changes to diffusion models, training objectives, datasets, and checkpoint implementations belong in the corresponding trainer repository.

HENTAI Studio is licensed under the [GNU General Public License v3.0](LICENSE). See [source provenance](SOURCE_PROVENANCE.md) for the project’s history and third-party notices.

## Before you start

- Discuss one focused problem before doing extensive work.
- Keep Studio independent of HENTAI, Lucy, and all model frameworks.
- Do not submit credentials, private paths, real job logs, datasets, weights, or checkpoints.
- Never stop an active training job to test an unrelated UI or documentation change. Use a temporary workspace and separate server port.

## Work locally

Use Python 3.11+ and Node 20+. From the repository root:

```sh
python -m pip install -e '.[dev]'
python -m pytest
npm test
git diff --check
```

The standard-library demo trainer and isolated workspaces are enough for application tests. No GPU or ML library is required. [Development](docs/DEVELOPMENT.md) covers browser acceptance, clean-wheel checks, and the optional Windows shell.

## Keep changes reviewable

- Explain the user-visible problem and resulting behavior.
- Add focused tests when behavior changes; use isolated fixtures for process tests.
- Preserve process identity checks, output confinement, and workspace ownership.
- Keep the dashboard usable when one output panel fails or the service disconnects.
- Update the relevant guide when changing the API, CLI, or project integration.
- Include desktop and mobile screenshots for substantial UI changes, using demo data without machine-specific paths.

For documentation screenshots, see [the capture instructions](docs/DEVELOPMENT.md#documentation-screenshots).

## Rights

By submitting a contribution, you represent that you have the right to submit it and agree to license it under the GNU General Public License v3.0, the same license as HENTAI Studio.
