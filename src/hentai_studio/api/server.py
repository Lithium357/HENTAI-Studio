import uvicorn
from fastapi import FastAPI


def serve(app: FastAPI, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")
