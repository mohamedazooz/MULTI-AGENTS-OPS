"""Async SQLAlchemy engine / session management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def init_engine(url: str, *, in_memory: bool = False) -> async_sessionmaker[AsyncSession]:
    """Create the global engine and session factory. Call once at startup."""
    global _engine, _session_factory
    kwargs: dict = {"pool_pre_ping": True}
    if in_memory or url.startswith("sqlite+aiosqlite:///:memory:"):
        kwargs = {
            "pool_pre_ping": True,
            "poolclass": __import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
            "connect_args": {"check_same_thread": False},
        }
    if url.startswith("sqlite+aiosqlite:///") and ":memory:" not in url:
        kwargs["connect_args"] = {"timeout": 30, "check_same_thread": False}
    _engine = create_async_engine(url, **kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine() -> None:
    """Drop engine references without async dispose (used by test harnesses)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


async def create_all() -> None:
    from . import models  # noqa: F401  (ensure tables are registered)

    if _engine is None:
        raise RuntimeError("Database engine not initialised")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    """FastAPI dependency yielding an AsyncSession (stable identity per request)."""

    if _session_factory is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    async with _session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Alias used by non-FastAPI callers (MCP tools, scheduler)."""
    return session_factory()
