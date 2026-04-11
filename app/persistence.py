from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row


@dataclass(slots=True)
class PersistenceSettings:
    """Environment-driven configuration for checkpoint persistence."""

    database_url: str
    setup_on_startup: bool = True

    @classmethod
    def from_env(cls) -> PersistenceSettings:
        """Load persistence settings from environment variables."""
        database_url: str | None = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL must be set to enable PostgreSQL-backed agent memory"
            )

        setup_flag: str = os.getenv("LANGGRAPH_SETUP_CHECKPOINTER", "true").lower()
        return cls(
            database_url=database_url,
            setup_on_startup=setup_flag not in {"0", "false", "no"},
        )


class PostgresCheckpointStore:
    """Wrap a psycopg connection and LangGraph Postgres checkpointer."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._settings = settings
        self._connection: Connection | None = None
        self._checkpointer: PostgresSaver | None = None

    def _initialize_checkpointer(self) -> tuple[Connection, PostgresSaver]:
        """Create the psycopg connection and checkpointer off the event loop."""
        connection = Connection.connect(
            self._settings.database_url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        try:
            checkpointer = PostgresSaver(
                connection,
                serde=JsonPlusSerializer(pickle_fallback=False),
            )
            if self._settings.setup_on_startup:
                checkpointer.setup()
        except Exception:
            connection.close()
            raise

        return connection, checkpointer

    async def open(self) -> None:
        """Connect to PostgreSQL and initialize the checkpointer."""
        self._connection, self._checkpointer = await asyncio.to_thread(
            self._initialize_checkpointer
        )

    async def close(self) -> None:
        """Close the underlying PostgreSQL connection."""
        if self._connection is not None:
            await asyncio.to_thread(self._connection.close)
        self._connection = None
        self._checkpointer = None

    @property
    def checkpointer(self) -> PostgresSaver:
        """Return the initialized LangGraph Postgres checkpointer."""
        if self._checkpointer is None:
            raise RuntimeError("PostgresCheckpointStore has not been opened")
        return self._checkpointer


@asynccontextmanager
async def managed_postgres_checkpointer() -> AsyncIterator[PostgresCheckpointStore]:
    """Create and close the PostgreSQL checkpoint store for app lifespan."""
    store = PostgresCheckpointStore(PersistenceSettings.from_env())
    await store.open()
    try:
        yield store
    finally:
        await store.close()
