"""Typed API error envelope for the control plane."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class OmnicpError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFound(OmnicpError):
    status_code = 404
    code = "not_found"


class Conflict(OmnicpError):
    status_code = 409
    code = "conflict"


class Unauthorized(OmnicpError):
    status_code = 401
    code = "unauthorized"


class Forbidden(OmnicpError):
    status_code = 403
    code = "forbidden"


class ValidationFailed(OmnicpError):
    status_code = 422
    code = "validation_failed"


class NotConfigured(OmnicpError):
    status_code = 501
    code = "not_configured"


async def omnicp_error_handler(_request: Request, exc: OmnicpError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
