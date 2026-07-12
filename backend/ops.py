"""Lightweight production helpers: env validation + simple rate limiting."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque

import uuid

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("atmos.ops")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach X-Request-Id for correlation across logs and client debugging."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response



def validate_startup_env() -> list[str]:
    """Return warnings; raise only on hard failures."""
    warnings: list[str] = []
    for key in ("MONGO_URL", "DB_NAME"):
        if not os.environ.get(key):
            raise RuntimeError(f"Missing required env: {key}")

    env = os.environ.get("ATMOS_ENV", "development").lower()
    if env in {"production", "prod"}:
        if os.environ.get("ATMOS_DISABLE_AUTH", "").lower() in {"1", "true", "yes"}:
            raise RuntimeError("ATMOS_DISABLE_AUTH cannot be enabled in production")
        cors = os.environ.get("CORS_ORIGINS", "*")
        if cors.strip() == "*":
            warnings.append("CORS_ORIGINS=* with credentials is unsafe in production")
        if os.environ.get("ATMOS_ALLOW_EMERGENT_FALLBACK", "0").lower() in {"1", "true", "yes"}:
            warnings.append("Emergent LLM fallback is enabled — prefer IDE-native quota")
        warnings.append("Production auth: use /api/auth/register + /api/auth/login (email/password)")

    for w in warnings:
        logger.warning(w)
    return warnings


class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding window limiter for mutating API routes."""

    def __init__(self, app, *, limit: int = 120, window: float = 60.0):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)
        # Allow local health / auth freely
        if path.rstrip("/").endswith(("/health", "/health/ready", "/health/live")):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self._hits[ip]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded — retry shortly")
        q.append(now)
        return await call_next(request)
