from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ..errors import StudioError
from .schemas import ErrorDetail, ErrorResponse


def error_response(
    status: int,
    code: str,
    message: str,
    details: list | None = None,
    headers: dict | None = None,
):
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or [])
    )
    return JSONResponse(payload.model_dump(), status_code=status, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StudioError)
    async def domain_error(request: Request, error: StudioError):
        details = [
            {
                **item,
                "field": "/body/"
                + "/".join(
                    str(part).replace("~", "~0").replace("/", "~1")
                    for part in item["field"]
                ),
            }
            for item in error.details
        ]
        return error_response(error.status, error.code, error.message, details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [
            {
                "field": "/"
                + "/".join(
                    str(part).replace("~", "~0").replace("/", "~1")
                    for part in item["loc"]
                ),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return error_response(
            422,
            "validation_error",
            "The request does not match the API schema.",
            details,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            error.status_code, "http_error"
        )
        return error_response(
            error.status_code, code, str(error.detail), headers=error.headers
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logging.getLogger("hentai_studio.api").exception(
            "Unhandled API error for %s %s", request.method, request.url.path
        )
        return error_response(
            500,
            "internal_error",
            "An unexpected server error occurred. Check the Studio server log.",
        )
