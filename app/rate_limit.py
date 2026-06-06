from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import HTTPException, Request
from redis.asyncio import Redis


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RateLimitSettings:
    """Environment-backed configuration for optional Redis API rate limiting."""

    redis_url: str
    limit: int
    window_seconds: int
    key_prefix: str = "rl"

    @classmethod
    def from_env(cls) -> RateLimitSettings | None:
        """Return settings only when rate limiting is explicitly enabled."""
        limit_raw = os.getenv("RATE_LIMIT_REQUESTS", "").strip()
        if not limit_raw:
            return None

        limit = max(0, int(limit_raw))
        if limit <= 0:
            return None

        redis_url = (
            os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
            or os.getenv("REDIS_URL", "").strip()
        )
        if not redis_url:
            return None

        window_raw = os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60").strip()
        return cls(
            redis_url=redis_url,
            limit=limit,
            window_seconds=max(1, int(window_raw or "60")),
            key_prefix=os.getenv("RATE_LIMIT_KEY_PREFIX", "rl").strip() or "rl",
        )


class RedisRateLimiter:
    """Simple fixed-window Redis rate limiter for protected API routes."""

    def __init__(self, settings: RateLimitSettings | None) -> None:
        self._settings = settings
        self._client: Redis | None = None

    async def open(self) -> None:
        """Connect to Redis when rate limiting is enabled."""
        if self._settings is None:
            return

        client = Redis.from_url(
            self._settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            await client.ping()
        except Exception as exc:
            self._client = None
            logger.warning("Redis unavailable, rate limiting disabled: %s", exc)
            await client.aclose()
            return

        self._client = client
        logger.info("Redis API rate limiting enabled.")

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def check(self, request: Request) -> None:
        """Raise 429 when the current subject exceeds the configured window budget."""
        if self._client is None or self._settings is None:
            return

        now = int(time.time())
        bucket = now // self._settings.window_seconds
        subject = self._subject_for_request(request)
        route_key = request.url.path.strip("/") or "root"
        redis_key = f"{self._settings.key_prefix}:{route_key}:{subject}:{bucket}"

        try:
            current = await self._client.incr(redis_key)
            if current == 1:
                await self._client.expire(redis_key, self._settings.window_seconds + 1)
        except Exception as exc:
            logger.warning("Redis rate-limit check failed, continuing without throttling: %s", exc)
            return

        if current > self._settings.limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    @staticmethod
    def _subject_for_request(request: Request) -> str:
        """Build a stable subject key from auth token or client identity."""
        authorization = request.headers.get("authorization", "").strip()
        if authorization:
            hashed = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:16]
            return f"auth:{hashed}"

        forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded_for:
            return f"ip:{forwarded_for}"

        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return f"ip:{real_ip}"

        client = getattr(request, "client", None)
        host = getattr(client, "host", "").strip() if client is not None else ""
        if host:
            return f"ip:{host}"

        return "anonymous"


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency that enforces the configured rate limit when enabled."""
    limiter: RedisRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    await limiter.check(request)


@asynccontextmanager
async def managed_rate_limiter() -> AsyncIterator[RedisRateLimiter]:
    """Create and close the optional Redis-backed API rate limiter."""
    limiter = RedisRateLimiter(RateLimitSettings.from_env())
    await limiter.open()
    try:
        yield limiter
    finally:
        await limiter.close()
