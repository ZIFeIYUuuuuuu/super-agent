from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.auth import require_api_key
from main import app


class ApiKeyAuthTests(unittest.TestCase):
    def test_require_api_key_allows_requests_when_api_key_is_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            require_api_key(None)

    def test_require_api_key_rejects_missing_header_when_api_key_is_set(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "secret-token"}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                require_api_key(None)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Missing Authorization Bearer token")

    def test_require_api_key_rejects_invalid_token(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "secret-token"}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                require_api_key("Bearer wrong-token")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "Invalid API token")

    def test_require_api_key_accepts_matching_bearer_token(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "secret-token"}, clear=True):
            require_api_key("Bearer secret-token")


class ProtectedRoutesTests(unittest.TestCase):
    def test_sensitive_v1_routes_include_api_key_dependency(self) -> None:
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
            self.assertIn(require_api_key, dependency_calls, route.path)

        self.assertEqual(seen_paths, protected_paths)
