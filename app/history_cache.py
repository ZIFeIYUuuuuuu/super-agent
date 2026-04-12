from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import AsyncIterator

from redis.asyncio import Redis

from app.models import CachedHistoryMessage


@dataclass(slots=True)
class HistoryCacheSettings:
    """Environment-backed configuration for Redis chat history caching."""

    redis_url: str
    key_prefix: str = "thread"
    max_messages: int = 40
    ttl_seconds: int = 60 * 60 * 24 * 30

    @classmethod
    def from_env(cls) -> HistoryCacheSettings | None:
        """Return cache settings when Redis is configured."""
        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            return None

        max_messages_raw = os.getenv("REDIS_HISTORY_MAX_MESSAGES", "40").strip()
        ttl_raw = os.getenv("REDIS_HISTORY_TTL_SECONDS", str(60 * 60 * 24 * 30)).strip()
        return cls(
            redis_url=redis_url,
            key_prefix=os.getenv("REDIS_HISTORY_KEY_PREFIX", "thread").strip() or "thread",
            max_messages=max(1, int(max_messages_raw or "40")),
            ttl_seconds=max(60, int(ttl_raw or str(60 * 60 * 24 * 30))),
        )


class HistoryCache:
    """Redis-backed hot cache for the most recent chat messages."""

    def __init__(self, settings: HistoryCacheSettings | None) -> None:
        self._settings = settings
        self._client: Redis | None = None

    async def open(self) -> None:
        """Connect to Redis when configured."""
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
            print(f"[history-cache] Redis unavailable, hot cache disabled: {exc}")
            await client.aclose()
            return
        self._client = client
        print("[history-cache] Redis hot cache enabled.")

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def append_messages(
        self,
        *,
        thread_id: str,
        messages: list[CachedHistoryMessage],
    ) -> None:
        """Append one or more messages to the hot history cache."""
        if self._client is None or self._settings is None or not messages:
            return

        key = self._key(thread_id)
        try:
            deduped = await self._dedupe_against_tail(key, messages)
        except Exception as exc:
            print(f"[history-cache] append dedupe skipped: {exc}")
            deduped = messages

        values = [json.dumps(item.model_dump(), ensure_ascii=False) for item in deduped]
        if not values:
            return
        try:
            pipeline = self._client.pipeline()
            pipeline.rpush(key, *values)
            pipeline.ltrim(key, -self._settings.max_messages, -1)
            pipeline.expire(key, self._settings.ttl_seconds)
            await pipeline.execute()
        except Exception as exc:
            print(f"[history-cache] append failed, request will continue without cache: {exc}")

    async def get_messages(self, thread_id: str) -> list[CachedHistoryMessage]:
        """Fetch the currently cached messages for one thread."""
        if self._client is None or self._settings is None or not thread_id.strip():
            return []

        key = self._key(thread_id)
        try:
            values = await self._client.lrange(key, 0, -1)
        except Exception as exc:
            print(f"[history-cache] read failed, returning empty history: {exc}")
            return []
        items: list[CachedHistoryMessage] = []
        for value in values:
            try:
                parsed = json.loads(value)
                items.append(CachedHistoryMessage.model_validate(parsed))
            except Exception:
                continue
        return items

    async def clear_thread(self, thread_id: str) -> None:
        """Delete the cached messages for one thread."""
        if self._client is None or self._settings is None or not thread_id.strip():
            return
        try:
            await self._client.delete(self._key(thread_id))
        except Exception as exc:
            print(f"[history-cache] clear failed: {exc}")

    async def is_enabled(self) -> bool:
        """Return whether Redis caching is currently active."""
        return self._client is not None and self._settings is not None

    @staticmethod
    def build_message(*, kind: str, content: str, created_at: str | None = None) -> CachedHistoryMessage:
        """Create one cached history message with a stable timestamp."""
        return CachedHistoryMessage(
            kind=kind,
            content=content,
            created_at=created_at or datetime.now(UTC).isoformat(),
        )

    def _key(self, thread_id: str) -> str:
        """Build the Redis key for one thread history list."""
        assert self._settings is not None
        return f"{self._settings.key_prefix}:{thread_id}:messages"

    async def _dedupe_against_tail(
        self,
        key: str,
        messages: list[CachedHistoryMessage],
    ) -> list[CachedHistoryMessage]:
        """Skip adjacent duplicate history messages to reduce noisy retries."""
        if self._client is None:
            return messages

        deduped: list[CachedHistoryMessage] = []
        last_raw = await self._client.lindex(key, -1)
        last_kind = ""
        last_content = ""
        if last_raw:
            try:
                parsed = CachedHistoryMessage.model_validate(json.loads(last_raw))
                last_kind = parsed.kind
                last_content = parsed.content
            except Exception:
                last_kind = ""
                last_content = ""

        for message in messages:
            if message.kind == last_kind and message.content == last_content:
                continue
            if deduped and deduped[-1].kind == message.kind and deduped[-1].content == message.content:
                continue
            deduped.append(message)
            last_kind = message.kind
            last_content = message.content
        return deduped


@asynccontextmanager
async def managed_history_cache() -> AsyncIterator[HistoryCache]:
    """Create and close the Redis history cache for app lifespan."""
    cache = HistoryCache(HistoryCacheSettings.from_env())
    await cache.open()
    try:
        yield cache
    finally:
        await cache.close()
