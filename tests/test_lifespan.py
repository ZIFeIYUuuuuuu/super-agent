from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from main import lifespan


class LifespanTests(unittest.TestCase):
    def test_lifespan_keeps_agent_runtime_open_until_shutdown(self) -> None:
        events: list[str] = []
        app = SimpleNamespace(state=SimpleNamespace())

        @asynccontextmanager
        async def context(name: str, value: object):
            events.append(f"enter:{name}")
            try:
                yield value
            finally:
                events.append(f"exit:{name}")

        async def run_case() -> None:
            with (
                patch("main.managed_postgres_checkpointer", lambda: context("checkpoint", SimpleNamespace(checkpointer="cp"))),
                patch("main.managed_knowledge_base", lambda: context("knowledge", "kb")),
                patch("main.managed_approval_store", lambda: context("approval", "approval-store")),
                patch("main.managed_history_cache", lambda: context("history", "history-cache")),
                patch("main.managed_rate_limiter", lambda: context("rate-limit", "rate-limiter")),
                patch("main.managed_mcp_client", lambda: context("mcp", "mcp-client")),
                patch("main.managed_agent_runtime", lambda *args: context("runtime", "runtime")),
            ):
                async with lifespan(app) as resources:
                    self.assertEqual(resources["agent_runtime"], "runtime")
                    self.assertEqual(app.state.agent_runtime, "runtime")
                    self.assertEqual(app.state.history_cache, "history-cache")
                    self.assertEqual(app.state.rate_limiter, "rate-limiter")
                    self.assertEqual(app.state.mcp_client, "mcp-client")
                    self.assertEqual(
                        events,
                        [
                            "enter:checkpoint",
                            "enter:knowledge",
                            "enter:approval",
                            "enter:history",
                            "enter:rate-limit",
                            "enter:mcp",
                            "enter:runtime",
                        ],
                    )

            self.assertEqual(
                events,
                [
                    "enter:checkpoint",
                    "enter:knowledge",
                    "enter:approval",
                    "enter:history",
                    "enter:rate-limit",
                    "enter:mcp",
                    "enter:runtime",
                    "exit:runtime",
                    "exit:mcp",
                    "exit:rate-limit",
                    "exit:history",
                    "exit:approval",
                    "exit:knowledge",
                    "exit:checkpoint",
                ],
            )

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
