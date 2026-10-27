"""Uvicorn configuration, including durable desktop-launcher logging."""

from pathlib import Path

import uvicorn
from fastapi import FastAPI


def serve(app: FastAPI, host: str, port: int, log_file: Path | None = None) -> None:
    options = {}
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        options["log_config"] = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}
            },
            "handlers": {
                "file": {
                    "class": "logging.FileHandler",
                    "filename": str(log_file),
                    "encoding": "utf-8",
                    "formatter": "plain",
                }
            },
            "loggers": {
                name: {"handlers": ["file"], "level": "INFO", "propagate": False}
                for name in (
                    "uvicorn",
                    "uvicorn.error",
                    "uvicorn.access",
                    "hentai_studio",
                )
            },
        }
    uvicorn.run(app, host=host, port=port, log_level="info", **options)
