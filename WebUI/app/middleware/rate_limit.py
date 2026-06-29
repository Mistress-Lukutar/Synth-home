"""Simple in-memory rate-limiting middleware."""

import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit mutating API requests by client IP."""

    def __init__(self, app, max_requests: int = 30, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
            client_host = request.client.host if request.client else "unknown"
            if not self._is_allowed(client_host):
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "error": "Rate limit exceeded"},
                )
        return await call_next(request)

    def _is_allowed(self, key: str) -> bool:
        now = time.time()
        timestamps = self._requests[key]
        # Evict expired entries
        timestamps[:] = [ts for ts in timestamps if now - ts < self.window_seconds]
        if len(timestamps) >= self.max_requests:
            return False
        timestamps.append(now)
        return True
