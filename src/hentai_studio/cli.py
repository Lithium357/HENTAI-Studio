from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hentai-studio", description="HENTAI Studio dashboard and causal-LM workloads")
    commands = parser.add_subparsers(dest="command", required=True)
    dashboard = commands.add_parser("dashboard", help="run the local training dashboard")
    dashboard.add_argument("--config", required=True)
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=7860)
    dashboard.add_argument("--storage-root", default="/mnt/d/HENTAI-Data", help="bulk storage root for Studio run resources")
    llm_audit = commands.add_parser("llm-audit", help="audit LLM JSONL text without GPU use or training")
    llm_audit.add_argument("--config", required=True)
    llm_validate = commands.add_parser("llm-validate", help="strictly validate an LLM workload configuration")
    llm_validate.add_argument("--config", required=True)
    llm_prepare = commands.add_parser("llm-prepare", help="create a new empty LLM run identity; does not train or use GPU")
    llm_prepare.add_argument("--config", required=True)
    llm_prepare.add_argument("--run-id", required=True)
    llm_prepare.add_argument("--display-name")
    llm_tokenizer = commands.add_parser("llm-tokenizer", help="train a run-local BPE tokenizer; reads configured text data but uses no GPU")
    llm_tokenizer.add_argument("--config", required=True)
    llm_tokenizer.add_argument("--output", required=True)
    llm_cache = commands.add_parser("llm-build-packed-cache", help="build a deterministic fixed-block token cache; reads text and uses no GPU")
    llm_cache.add_argument("--config", required=True)
    llm_cache.add_argument("--output", help="cache directory; defaults to dataset.packed_cache")
    llm_cache.add_argument("--overwrite", action="store_true", help="replace an incompatible cache only after a complete rebuild")
    llm_smoke = commands.add_parser("llm-smoke", help="run a synthetic causal-LM update; does not read dataset text")
    llm_smoke.add_argument("--config", required=True)
    llm_smoke.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    llm_smoke.add_argument("--tiny", action="store_true", help="use a tiny synthetic model instead of the configured architecture")
    llm_train = commands.add_parser("llm-train", help="train a prepared scratch or LoRA LLM run; reads text and may use GPU")
    llm_train.add_argument("--config", required=True)
    llm_train.add_argument("--no-resume", action="store_true")
    llm_train.add_argument("--device", choices=("cpu", "cuda"))
    llm_checkpoint = commands.add_parser("llm-checkpoint-verify", help="read-only integrity check for a completed LoRA checkpoint")
    llm_checkpoint.add_argument("--run-dir", required=True)
    llm_checkpoint.add_argument("--step", required=True, type=int)
    llm_normalize = commands.add_parser("llm-normalize-erp", help="stream a CSV roleplay archive into cleaned thread-preserving JSONL; does not train")
    llm_normalize.add_argument("--source", required=True)
    llm_normalize.add_argument("--output", required=True)
    llm_normalize.add_argument("--limit-files", type=int)
    studio = commands.add_parser("studio", help="run the workload-neutral local Studio API")
    studio.add_argument("--storage-root", required=True)
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=7861)
    dashboard.add_argument("--project", required=True, help="HENTAI diffusion checkout containing runs, configs, and training scripts")
    studio.add_argument("--project", required=True, help="HENTAI diffusion checkout containing runs")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "dashboard":
        from .dashboard import run_dashboard

        run_dashboard(Path(args.project).resolve(), args.config, args.host, args.port, args.storage_root)
    elif args.command == "llm-audit":
        from .workloads.llm.config import load_llm_config
        from .workloads.llm.dataset import audit_jsonl

        config = load_llm_config(args.config)
        print(json.dumps(audit_jsonl(config.dataset).as_dict(), indent=2))
    elif args.command == "llm-validate":
        from .workloads.llm.config import load_llm_config

        config = load_llm_config(args.config)
        print(f"Valid LLM config: {config.mode} -> {config.output}")
    elif args.command == "llm-prepare":
        from .workloads.llm.config import load_llm_config
        from .workloads.llm.prepare import prepare_run

        print(prepare_run(load_llm_config(args.config), args.config, args.run_id, args.display_name))
    elif args.command == "llm-tokenizer":
        from .workloads.llm.config import load_llm_config
        from .workloads.llm.tokenizer import train_bpe

        config = load_llm_config(args.config)
        print(train_bpe(config.dataset, config.tokenizer, args.output))
    elif args.command == "llm-build-packed-cache":
        from transformers import AutoTokenizer

        from .workloads.llm.config import load_llm_config
        from .workloads.llm.packed_cache import build_packed_cache

        config = load_llm_config(args.config)
        if config.tokenizer.mode != "base_model" or not config.tokenizer.base_model:
            raise ValueError("packed-cache construction currently requires tokenizer.mode=base_model")
        output = args.output or config.dataset.packed_cache
        if not output:
            raise ValueError("set dataset.packed_cache or pass --output")
        tokenizer = AutoTokenizer.from_pretrained(config.tokenizer.base_model, local_files_only=True)
        manifest = build_packed_cache(config, tokenizer, output, overwrite=args.overwrite)
        print(json.dumps(asdict(manifest), indent=2))
    elif args.command == "llm-smoke":
        from .workloads.llm.config import load_llm_config
        from .workloads.llm.smoke import smoke_test

        print(json.dumps(smoke_test(load_llm_config(args.config), device=args.device, tiny=args.tiny), indent=2))
    elif args.command == "llm-train":
        from .workloads.llm.config import load_llm_config
        from .workloads.llm.training import train_scratch

        config = load_llm_config(args.config)
        if config.mode == "lora":
            if args.device not in (None, "cuda"):
                raise ValueError("LoRA CPT is GPU-only on this local backend")
            from .workloads.llm.lora_cpt import run_lora_cpt

            run_lora_cpt(config, resume=not args.no_resume)
        elif config.mode == "scratch":
            train_scratch(config, config_path=args.config, resume=not args.no_resume, device=args.device)
        else:
            raise ValueError(f"unsupported LLM training mode: {config.mode}")
    elif args.command == "llm-checkpoint-verify":
        from .workloads.llm.checkpoint import verify_lora_checkpoint

        report = verify_lora_checkpoint(args.run_dir, args.step)
        print(json.dumps(report, indent=2))
        if not report["complete"]:
            return 2
    elif args.command == "llm-normalize-erp":
        from .workloads.llm.normalization import normalize_csv_archive

        print(json.dumps(asdict(normalize_csv_archive(args.source, args.output, limit_files=args.limit_files)), indent=2))
    elif args.command == "studio":
        from .studio import run_studio

        run_studio(Path(args.project).resolve(), args.storage_root, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
