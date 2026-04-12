from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row

ApprovalStatusLiteral = Literal["pending", "approved", "rejected"]


@dataclass(slots=True)
class ApprovalRecord:
    """One persisted human approval request."""

    approval_id: str
    thread_id: str
    status: ApprovalStatusLiteral
    tool_name: str
    risk_level: str
    summary: str
    tool_args: dict[str, Any]
    comment: str | None
    created_at: str
    updated_at: str
    resumed_at: str | None


@dataclass(slots=True)
class ApprovalStoreSettings:
    """Environment-backed settings for approval persistence."""

    database_url: str
    connect_timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> ApprovalStoreSettings:
        """Load the backing PostgreSQL DSN from environment variables."""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be set to enable approval persistence")
        timeout_raw = os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "5").strip()
        return cls(
            database_url=database_url,
            connect_timeout_seconds=max(1, int(timeout_raw or "5")),
        )


class ApprovalStore:
    """Persistent approval registry used by the Human-in-the-loop flow."""

    def __init__(self, settings: ApprovalStoreSettings | None = None) -> None:
        self._settings = settings or ApprovalStoreSettings.from_env()

    async def open(self) -> None:
        """Create the approval table if it does not yet exist."""
        await asyncio.to_thread(self._open_sync)

    async def close(self) -> None:
        """Close hook for symmetry with app lifespan management."""
        await asyncio.sleep(0)

    async def create_pending(
        self,
        *,
        thread_id: str,
        tool_name: str,
        risk_level: str,
        summary: str,
        tool_args: dict[str, Any],
    ) -> ApprovalRecord:
        """Insert a new pending approval request."""
        return await asyncio.to_thread(
            self._create_pending_sync,
            thread_id,
            tool_name,
            risk_level,
            summary,
            tool_args,
        )

    async def get_latest_for_thread(self, thread_id: str) -> ApprovalRecord | None:
        """Fetch the latest approval entry for a thread."""
        return await asyncio.to_thread(self._get_latest_for_thread_sync, thread_id)

    async def get_by_id(self, approval_id: str) -> ApprovalRecord | None:
        """Fetch one approval entry by identifier."""
        return await asyncio.to_thread(self._get_by_id_sync, approval_id)

    async def list_pending(self, thread_id: str | None = None) -> list[ApprovalRecord]:
        """List pending approvals, optionally filtered by thread ID."""
        return await asyncio.to_thread(self._list_pending_sync, thread_id)

    async def get_pending_for_thread(self, thread_id: str) -> ApprovalRecord | None:
        """Return latest pending approval for one thread, if any."""
        items = await self.list_pending(thread_id=thread_id)
        return items[0] if items else None

    async def decide(
        self,
        *,
        thread_id: str,
        approval_id: str,
        decision: ApprovalStatusLiteral,
        comment: str | None = None,
    ) -> ApprovalRecord:
        """Record a human approval or rejection decision."""
        return await asyncio.to_thread(
            self._decide_sync,
            thread_id,
            approval_id,
            decision,
            comment,
        )

    async def get_resumable_for_thread(self, thread_id: str) -> ApprovalRecord | None:
        """Return the newest approved/rejected record awaiting resume."""
        return await asyncio.to_thread(self._get_resumable_for_thread_sync, thread_id)

    async def mark_resumed(self, approval_id: str) -> ApprovalRecord | None:
        """Mark an approval request as consumed by graph resumption."""
        return await asyncio.to_thread(self._mark_resumed_sync, approval_id)

    def _open_sync(self) -> None:
        """Create the approval table and indexes."""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS human_approvals (
                        approval_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        tool_args JSONB NOT NULL,
                        comment TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        resumed_at TIMESTAMPTZ NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_human_approvals_thread
                    ON human_approvals (thread_id, created_at DESC)
                    """
                )

    def _create_pending_sync(
        self,
        thread_id: str,
        tool_name: str,
        risk_level: str,
        summary: str,
        tool_args: dict[str, Any],
    ) -> ApprovalRecord:
        approval_id = uuid4().hex
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO human_approvals (
                        approval_id,
                        thread_id,
                        status,
                        tool_name,
                        risk_level,
                        summary,
                        tool_args
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        approval_id,
                        thread_id,
                        "pending",
                        tool_name,
                        risk_level,
                        summary,
                        json.dumps(tool_args, ensure_ascii=False),
                    ),
                )
        record = self._get_by_id_sync(approval_id)
        if record is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Approval record was not persisted successfully")
        return record

    def _get_latest_for_thread_sync(self, thread_id: str) -> ApprovalRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM human_approvals
                    WHERE thread_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (thread_id,),
                )
                row = cursor.fetchone()
        return self._row_to_record(row)

    def _get_by_id_sync(self, approval_id: str) -> ApprovalRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM human_approvals
                    WHERE approval_id = %s
                    LIMIT 1
                    """,
                    (approval_id,),
                )
                row = cursor.fetchone()
        return self._row_to_record(row)

    def _list_pending_sync(self, thread_id: str | None = None) -> list[ApprovalRecord]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                if thread_id:
                    cursor.execute(
                        """
                        SELECT *
                        FROM human_approvals
                        WHERE status = 'pending'
                          AND thread_id = %s
                        ORDER BY created_at DESC
                        """,
                        (thread_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT *
                        FROM human_approvals
                        WHERE status = 'pending'
                        ORDER BY created_at DESC
                        """
                    )
                rows = cursor.fetchall()
        return [record for row in rows if (record := self._row_to_record(row)) is not None]

    def _decide_sync(
        self,
        thread_id: str,
        approval_id: str,
        decision: ApprovalStatusLiteral,
        comment: str | None,
    ) -> ApprovalRecord:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")

        existing = self._get_by_id_sync(approval_id)
        if existing is None:
            raise ValueError("approval_id does not exist")
        if existing.thread_id != thread_id:
            raise ValueError("thread_id does not match the approval request")

        if existing.status in {"approved", "rejected"}:
            if existing.status == decision:
                return existing
            raise ValueError("approval request already has the opposite decision recorded")

        if existing.status != "pending":
            raise ValueError(f"approval request is not pending: {existing.status}")

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE human_approvals
                    SET status = %s,
                        comment = %s,
                        updated_at = NOW()
                    WHERE approval_id = %s
                    """,
                    (decision, comment, approval_id),
                )
        updated = self._get_by_id_sync(approval_id)
        if updated is None:  # pragma: no cover - defensive guard
            raise RuntimeError("approval request disappeared after decision update")
        return updated

    def _get_resumable_for_thread_sync(self, thread_id: str) -> ApprovalRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM human_approvals
                    WHERE thread_id = %s
                      AND status IN ('approved', 'rejected')
                      AND resumed_at IS NULL
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (thread_id,),
                )
                row = cursor.fetchone()
        return self._row_to_record(row)

    def _mark_resumed_sync(self, approval_id: str) -> ApprovalRecord | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE human_approvals
                    SET resumed_at = COALESCE(resumed_at, NOW()),
                        updated_at = NOW()
                    WHERE approval_id = %s
                    """,
                    (approval_id,),
                )
        return self._get_by_id_sync(approval_id)

    @staticmethod
    def _row_to_record(row: dict[str, Any] | None) -> ApprovalRecord | None:
        if row is None:
            return None
        tool_args = row["tool_args"]
        if isinstance(tool_args, str):
            tool_args = json.loads(tool_args)
        return ApprovalRecord(
            approval_id=str(row["approval_id"]),
            thread_id=str(row["thread_id"]),
            status=str(row["status"]),
            tool_name=str(row["tool_name"]),
            risk_level=str(row["risk_level"]),
            summary=str(row["summary"]),
            tool_args=dict(tool_args or {}),
            comment=str(row["comment"]) if row["comment"] is not None else None,
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
            resumed_at=row["resumed_at"].isoformat() if row["resumed_at"] is not None else None,
        )

    def _connection(self) -> Connection:
        """Create a short-lived PostgreSQL connection for one operation."""
        return Connection.connect(
            self._settings.database_url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
            connect_timeout=self._settings.connect_timeout_seconds,
        )


@asynccontextmanager
async def managed_approval_store() -> AsyncIterator[ApprovalStore]:
    """Create and close the approval store for app lifespan."""
    store = ApprovalStore(ApprovalStoreSettings.from_env())
    await store.open()
    try:
        yield store
    finally:
        await store.close()
