"""RFC 7807 structured errors (Phase 3).

Every API failure is a ``application/problem+json`` document with a machine-readable
``type``, a stable ``code``, a human ``detail``, a ``correlation_id`` and a
``retryable`` flag (CONTRACTS: "RFC 7807-compatible structured errors with
machine-readable type, code, detail, correlation_id, and retryability").
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

#: Base URL for the machine-readable problem ``type`` URIs.
PROBLEM_BASE = "urn:umd:problem"


class ApiError(Exception):
    """A structured, retryable-aware API error (mapped to RFC 7807)."""

    status: int = 400
    code: str = "bad_request"
    retryable: bool = False

    def __init__(
        self,
        detail: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retryable: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.extra = extra or {}


class NotFoundError(ApiError):
    status = 404
    code = "not_found"


class ConflictError(ApiError):
    status = 409
    code = "conflict"
    retryable = True


class UnauthorizedError(ApiError):
    status = 401
    code = "unauthorized"


class ForbiddenError(ApiError):
    status = 403
    code = "forbidden"


class RateLimitedError(ApiError):
    status = 429
    code = "rate_limited"
    retryable = True


class QueryCostExceededError(ApiError):
    status = 422
    code = "query_cost_exceeded"


class ConsistencyLagError(ApiError):
    """A token-bearing Tier-1 read that could not catch up within the lag budget."""

    status = 503
    code = "consistency_lag"
    retryable = True


def problem_document(
    *,
    status: int,
    type_: str,
    code: str,
    detail: str,
    correlation_id: str | None,
    retryable: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the RFC 7807 ``application/problem+json`` body."""
    doc: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}:{type_}",
        "title": code,
        "status": status,
        "code": code,
        "detail": detail,
        "retryable": retryable,
    }
    if correlation_id:
        doc["correlation_id"] = correlation_id
    if extra:
        doc.update(extra)
    return doc


def json_problem(
    status: int,
    *,
    type_: str,
    code: str,
    detail: str,
    correlation_id: str | None = None,
    retryable: bool = False,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    doc = problem_document(
        status=status,
        type_=type_,
        code=code,
        detail=detail,
        correlation_id=correlation_id,
        retryable=retryable,
        extra=extra,
    )
    resp_headers = {"content-type": "application/problem+json"}
    if headers:
        resp_headers.update(headers)
    return JSONResponse(status_code=status, content=doc, headers=resp_headers)


def _correlation(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None) or request.headers.get("x-request-id")


def register_error_handlers(app: Any) -> None:
    """Install RFC 7807 exception handlers on the FastAPI app."""

    @app.exception_handler(ApiError)  # type: ignore[untyped-decorator]
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:  # noqa: ANN001
        headers: dict[str, str] | None = None
        if exc.extra:
            if "retry_after" in exc.extra:
                headers = {"retry-after": str(exc.extra["retry_after"])}
            if headers is None:
                headers = {}
            if "x-consistency" in exc.extra:
                headers["x-consistency"] = str(exc.extra["x-consistency"])
            if "x-rebuild-estimate" in exc.extra:
                headers["x-rebuild-estimate"] = str(exc.extra["x-rebuild-estimate"])
            if headers == {}:
                headers = None
        return json_problem(
            exc.status,
            type_=exc.code,
            code=exc.code,
            detail=exc.detail,
            correlation_id=_correlation(request),
            retryable=exc.retryable,
            extra=exc.extra,
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)  # type: ignore[untyped-decorator]
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return json_problem(
            exc.status_code,
            type_="http_error",
            code="http_error",
            detail=str(exc.detail),
            correlation_id=_correlation(request),
            retryable=exc.status_code in (408, 425, 429, 500, 502, 503, 504),
        )

    @app.exception_handler(RequestValidationError)  # type: ignore[untyped-decorator]
    async def _validation_error(  # noqa: ANN001
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return json_problem(
            422,
            type_="validation_error",
            code="validation_error",
            detail="request validation failed",
            correlation_id=_correlation(request),
            retryable=False,
            extra={"errors": exc.errors()},
        )


__all__ = [
    "ApiError",
    "NotFoundError",
    "ConflictError",
    "UnauthorizedError",
    "ForbiddenError",
    "RateLimitedError",
    "QueryCostExceededError",
    "ConsistencyLagError",
    "problem_document",
    "json_problem",
    "register_error_handlers",
]
