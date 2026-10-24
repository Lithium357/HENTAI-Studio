# HENTAI Studio

HENTAI Studio is the local control room for [HENTAI](https://github.com/Lithium357/HENTAI): a web dashboard, local API, Windows WebView2 shell, AMD telemetry, and causal-LM workload tools.

Diffusion model definitions, training, checkpoint sampling, and image generation remain in HENTAI. Studio installs as the distinct `hentai_studio` Python package and `hentai-studio` command, so the two projects can share an environment without overwriting each other's modules.

## Install

Clone both repositories. Use matching split revisions (HENTAI 0.2 and Studio 0.2) until both changes are merged.

```bash
git clone https://github.com/Lithium357/HENTAI.git
git clone https://github.com/Lithium357/HENTAI-Studio.git
cd HENTAI-Studio
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ../HENTAI -e '.[dev]'
```

Install the hardware-appropriate PyTorch build separately for diffusion training; HENTAI's `scripts/setup_wsl.sh` prepares its reference ROCm environment. Studio's stop/resume controls launch watchdogs from the engine checkout, which use **HENTAI/.venv**, so retain that environment as well. CPU checkpoint sampling uses the Studio environment; install CPU Torch there, or the matching ROCm build when sharing a GPU environment.

For language-model training, tokenization, packed caches, and checkpoint chat:

```bash
python -m pip install -e '.[llm]'
```

The base dashboard and metadata API do not import Torch, Diffusers, or Transformers during startup. Install both local repositories in the same pip transaction because `scratchtag-diffusion` is a private source dependency and is not published on PyPI.

## Launch

```bash
hentai-studio dashboard \
  --project /path/to/HENTAI \
  --config configs/rx7800xt-scratch-v3-x4-512.json \
  --storage-root /mnt/d/HENTAI-Data \
  --host 127.0.0.1 --port 7860

# API-only process, without the dashboard frontend:
hentai-studio studio --project /path/to/HENTAI \
  --storage-root /mnt/d/HENTAI-Data --port 7861
```

Open `http://127.0.0.1:7860`. `--project` always refers to the **HENTAI engine checkout**, regardless of the current directory. Relative diffusion configs, data paths, runs, and watchdogs resolve from that project. LLM commands resolve their own config paths from the current directory. Choose an existing writable directory for `--storage-root`; managed LLM preparation creates run directories beneath it.

The dashboard provides VAE/diffuser progress, stop/resume and promotion controls, CPU checkpoint sampling, historical checkpoint selection, CSV exports, process telemetry, and an LLM workspace with CPU checkpoint chat. Training and samples are explicit actions; merely starting the dashboard does not start training.

## Windows launcher and telemetry

Build `windows/HENTAIStudio/HENTAIStudio.csproj` with the .NET SDK, or run `windows/HENTAIStudio/build.ps1` to publish and install the shell with shortcuts. The existing launcher defaults are retained; configure these variables for another machine:

| Variable | Meaning |
|---|---|
| `HENTAI_WSL_DISTRO` | WSL distribution (default `Ubuntu`) |
| `HENTAI_WSL_PROJECT` | Engine checkout (default `/home/masonturlington/HENTAI`) |
| `HENTAI_STUDIO_WSL_PROJECT` | Studio checkout and `.venv` (default `/home/masonturlington/HENTAI-Studio`) |
| `HENTAI_CONFIG` | Diffusion config relative to the engine checkout |
| `HENTAI_HARDWARE_PROBE` | Optional telemetry executable override, set inside WSL |

The bundled telemetry executable is installed with the Python package. Its Rust source is in `hardware_probe/` with ADLX sources and licenses under `vendor/ADLX/`. Rebuild with `cargo build --manifest-path hardware_probe/Cargo.toml --release`, then copy `hardware_probe/target/release/hentai-hardware-probe.exe` to `src/hentai_studio/bin/hardware_probe.exe` before building a wheel. Telemetry can be unavailable on unsupported platforms without preventing dashboard startup.

## Documentation and verification

- [Migration and repository boundary](docs/MIGRATION.md)
- [Dashboard](docs/DASHBOARD.md)
- [CLI](docs/CLI.md)
- [Development](docs/DEVELOPMENT.md)
- [LLM dataset contract](docs/LLM_DATASET.md)
- [LLM training](docs/LLM_TRAINING.md)
- [LLM throughput plan](docs/LLM_THROUGHPUT_PLAN.md)
- [ROCm experiment log](docs/ROCM_EXPERIMENT_LOG.md)

```bash
python -m pip install -e ../HENTAI -e '.[dev,llm]'
python -m pytest -q
git diff --check
```

No datasets, model weights, token caches, logs, or run state are shipped. See [source provenance](SOURCE_PROVENANCE.md) for the extracted source's original terms and upstream revision.
