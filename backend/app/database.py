import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.logging import logger


class SafeAsyncSession(AsyncSession):
    """Close sessions safely when an SSE request is cancelled mid-query.

    asyncmy can lose its underlying writer while SQLAlchemy is doing the
    rollback performed by ``AsyncSession.close``.  The resulting cleanup
    exception is not an application failure and must not become an unhandled
    task exception.  Invalidating the connection is the safe fallback.
    """

    async def close(self) -> None:
        try:
            await super().close()
        except asyncio.CancelledError:
            try:
                await asyncio.shield(super().invalidate())
            except BaseException as cleanup_error:
                logger().debug(
                    "database session invalidation failed after cancellation",
                    error_type=type(cleanup_error).__name__,
                )
            raise
        except Exception:
            try:
                await asyncio.shield(super().invalidate())
            except BaseException as cleanup_error:
                logger().debug(
                    "database session invalidation failed after close error",
                    error_type=type(cleanup_error).__name__,
                )


class Database:
    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        if parsed.drivername != "mysql+asyncmy":
            raise ValueError("database URL must use mysql+asyncmy")
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            isolation_level="READ COMMITTED",
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=SafeAsyncSession,
            expire_on_commit=False,
        )

    async def sessions(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
