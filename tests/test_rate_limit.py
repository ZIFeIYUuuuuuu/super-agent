from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.rate_limit import RateLimitSettings, RedisRateLimiter, enforce_rate_limit
from main import app


class RateLimitSettingsTests(unittest.TestCase):
    def test_from_env_returns_none_when_limit_is_not_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(RateLimitSettings.from_env())

    def test_from_env_returns_none_when_redis_url_is_missing(self) -> None:
        with patch.dict(os.environ, {"RATE_LIMIT_REQUESTS": "10"}, clear=True):
            self.assertIsNone(RateLimitSettings.from_env())

    def test_from_env_uses_redis_url_fallback_and_parses_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RATE_LIMIT_REQUESTS": "12",
                "RATE_LIMIT_WINDOW_SECONDS": "90",
                "RATE_LIMIT_KEY_PREFIX": "api-rl",
                "REDIS_URL": "redis://localhost:6379/0",
            },
            clear=True,
        ):
            settings = RateLimitSettings.from_env()

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.redis_url, "redis://localhost:6379/0")
        self.assertEqual(settings.limit, 12)
        self.assertEqual(settings.window_seconds, 90)
        self.assertEqual(settings.key_prefix, "api-rl")


class RateLimiterDependencyTests(unittest.TestCase):
    def test_subject_prefers_authorization_header_hash(self) -> None:
        request = SimpleNamespace(
            headers={"authorization": "Bearer secret-token"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        subject = RedisRateLimiter._subject_for_request(request)  # type: ignore[arg-type]
        self.assertTrue(subject.startswith("auth:"))
        self.assertNotIn("secret-token", subject)

    def test_subject_falls_back_to_forwarded_ip(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.7, 10.0.0.8"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        subject = RedisRateLimiter._subject_for_request(request)  # type: ignore[arg-type]
        self.assertEqual(subject, "ip:198.51.100.7")

    def test_enforce_rate_limit_skips_when_limiter_is_missing(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        asyncio.run(enforce_rate_limit(request))  # type: ignore[arg-type]

    def test_enforce_rate_limit_calls_active_limiter(self) -> None:
        limiter = SimpleNamespace(check=AsyncMock())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(rate_limiter=limiter)))
        asyncio.run(enforce_rate_limit(request))  # type: ignore[arg-type]
        limiter.check.assert_awaited_once_with(request)

    def test_check_raises_429_after_limit_is_exceeded(self) -> None:
        limiter = RedisRateLimiter(
            RateLimitSettings(
                redis_url="redis://localhost:6379/0",
                limit=2,
                window_seconds=60,
            )
        )
        limiter._client = SimpleNamespace(incr=AsyncMock(return_value=3), expire=AsyncMock())  # type: ignore[assignment]
        request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
            url=SimpleNamespace(path="/v1/chat/completions"),
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(limiter.check(request))  # type: ignore[arg-type]

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "Rate limit exceeded")


class ProtectedRoutesTests(unittest.TestCase):
    def test_sensitive_v1_routes_include_rate_limit_dependency(self) -> None:
        protected_paths = {
            "/v1/approvals/decision",
            "/v1/approvals/pending/{thread_id}",
            "/v1/approvals/resume",
            "/v1/approvals/{approval_id}/decision",
            "/v1/chat/completions",
            "/v1/knowledge/documents",
            "/v1/knowledge/status",
            "/v1/knowledge/upload",
            "/v1/threads/{thread_id}/history",
        }

        seen_paths: set[str] = set()
        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path not in protected_paths:
                continue
            seen_paths.add(route.path)
            dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
            self.assertIn(enforce_rate_limit, dependency_calls, route.path)

        self.assertEqual(seen_paths, protected_paths)
