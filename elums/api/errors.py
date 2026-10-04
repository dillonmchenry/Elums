"""The one error shape, established M4 so every router from here on reuses it.

    {"error": {"code": "not_found", "message": "...", "details": {...}}}

`code` is a stable machine-readable snake_case string (not an HTTP status —
the frontend branches on `code`, not on parsing prose). `details` is
optional and endpoint-specific (e.g. validation field errors).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Stable snake_case codes for the handful of HTTPExceptions FastAPI/Starlette
# raise themselves (unmatched route, wrong method) — anything we raise
# ourselves should use ApiError with an explicit code instead.
_STATUS_CODE_NAMES: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    # Registered against Starlette's base HTTPException, not fastapi's
    # subclass: `fastapi.HTTPException` IS A subclass of
    # `starlette.exceptions.HTTPException`, but Starlette's own router
    # raises the BASE class directly for unmatched routes (404) and wrong
    # methods (405) — before FastAPI-level code ever runs. A handler
    # registered for the fastapi subclass alone never catches those,
    # since exception-handler dispatch walks the MRO *up* from the raised
    # instance, not down to subclasses. Verified directly Oct 3 2026 (M5)
    # by writing a test for it: the subclass-only registration silently
    # let framework 404s fall through to Starlette's default
    # {"detail": "..."} shape, breaking the "one error shape" convention
    # for exactly the routes a client is most likely to hit by mistake.
    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODE_NAMES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body("validation_error", "Request failed validation.", {"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("internal_error", "An unexpected error occurred."),
        )
