"""Structured request/response logging middleware."""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response with timing and status code."""

    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(exc),
                duration_ms=round(duration_ms, 2),
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_processed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
