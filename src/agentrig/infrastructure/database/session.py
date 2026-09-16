"""async SQLAlchemy Engine 与 Session 生命周期。"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from .orm import Base


class DatabaseSchemaError(RuntimeError):
    """数据库未迁移到与当前代码匹配的 Alembic revision。"""


def normalize_database_url(url: str) -> str:
    if not url:
        return "sqlite+aiosqlite:///./.agentrig/agentrig.db"
    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def prepare_database_url(url: str) -> str:
    """规范化数据库 URL，并为文件 SQLite 创建父目录。"""

    normalized = normalize_database_url(url)
    if normalized.startswith("sqlite+aiosqlite:///"):
        raw_path = normalized.removeprefix("sqlite+aiosqlite:///")
        if raw_path and raw_path != ":memory:":
            Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return normalized


class Database:
    def __init__(self, url: str = "", *, echo: bool = False) -> None:
        self.url = prepare_database_url(url)
        engine_options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
        self._session_lock: asyncio.Lock | None = None
        self._sqlite_memory_anchor: sqlite3.Connection | None = None
        engine_url = self.url
        if self.url == "sqlite+aiosqlite:///:memory:":
            # A cancelled aiosqlite operation can invalidate the pooled connection.
            # A plain ``:memory:`` database would then disappear with that connection,
            # so keep a private shared-memory database alive for this Database instance.
            memory_name = f"file:agentrig_{uuid4().hex}?mode=memory&cache=shared"
            self._sqlite_memory_anchor = sqlite3.connect(
                memory_name,
                uri=True,
                check_same_thread=False,
            )
            engine_url = f"sqlite+aiosqlite:///{memory_name}&uri=true"
            engine_options["poolclass"] = StaticPool
            # SQLite 内存库只能复用同一连接；并发 AsyncSession 会让一个请求的
            # rollback/commit 干扰另一个请求。串行化数据库临界区只用于该测试/
            # Demo 形态，文件 SQLite 与 PostgreSQL 仍保持正常连接池并发。
            self._session_lock = asyncio.Lock()
        self.engine: AsyncEngine = create_async_engine(engine_url, **engine_options)
        self.sessions = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        if self.url.startswith("sqlite+aiosqlite:"):
            event.listen(self.engine.sync_engine, "connect", self._configure_sqlite)

    @property
    def is_ephemeral(self) -> bool:
        """内存 SQLite 仅用于测试/Demo，可直接由 ORM metadata 建表。"""

        return self.url == "sqlite+aiosqlite:///:memory:"

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def initialize_schema(self) -> None:
        """测试内存库自动建表；持久化数据库必须已由 Alembic 迁移。"""

        if self.is_ephemeral:
            await self.create_schema()
            return
        await self.require_current_schema()

    async def require_current_schema(self) -> None:
        """拒绝未初始化、未纳入 Alembic 或 revision 落后的持久化数据库。"""

        from .migrations import migration_heads

        expected = set(migration_heads())
        async with self.engine.connect() as connection:
            current = set(await connection.run_sync(self._schema_revisions))
        if current == expected:
            return
        if not current:
            raise DatabaseSchemaError(
                "database schema is not initialized by Alembic; "
                "run `agentrig db upgrade` before starting the service"
            )
        raise DatabaseSchemaError(
            "database schema revision mismatch: "
            f"current={sorted(current)!r}, expected={sorted(expected)!r}; "
            "run `agentrig db upgrade` before starting the service"
        )

    @staticmethod
    def _schema_revisions(connection: Connection) -> tuple[str, ...]:
        inspector = inspect(connection)
        if not inspector.has_table("alembic_version"):
            return ()
        rows = connection.execute(text("SELECT version_num FROM alembic_version"))
        return tuple(str(value) for value in rows.scalars())

    async def drop_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._session_lock is not None:
            async with self._session_lock:
                async with self._managed_session() as session:
                    yield session
            return
        async with self._managed_session() as session:
            yield session

    @asynccontextmanager
    async def _managed_session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()
        if self._sqlite_memory_anchor is not None:
            self._sqlite_memory_anchor.close()
            self._sqlite_memory_anchor = None
