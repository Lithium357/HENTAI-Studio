"""Studio starts a workspace; training commands belong to external projects."""

import argparse
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hentai-studio", description="Local training project manager"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="manage local training projects")
    serve.add_argument("--workspace", type=Path, default=Path.home() / ".hentai-studio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.add_argument(
        "--log-file", type=Path, help="append server logs to a file (desktop launcher)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from .studio import run_studio

    try:
        run_studio(
            args.workspace.expanduser().resolve(),
            args.host,
            args.port,
            args.log_file.expanduser().resolve() if args.log_file else None,
        )
    except (RuntimeError, OSError) as error:
        _parser().exit(1, f"Studio could not start: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
