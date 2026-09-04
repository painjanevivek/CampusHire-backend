from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings


def database_engine_options(settings: Settings) -> dict[str, Any]:
    """Keep each process pool small while reusing warm database connections."""
    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout_seconds,
        "pool_recycle": settings.database_pool_recycle_seconds,
        "pool_pre_ping": True,
    }


def database_url_for_asyncpg(database_url: str) -> URL:
    """Translate a generic Neon/libpq URL into asyncpg connection options.

    Neon exposes connection strings for several PostgreSQL clients. Its generic
    URL can include ``channel_binding`` and ``sslmode``; SQLAlchemy otherwise
    forwards those names to asyncpg, whose connect function rejects them.
    ``sslmode=require`` becomes asyncpg's equivalent ``ssl=require`` option.
    """
    url = make_url(database_url)
    query = dict(url.query)
    query.pop("channel_binding", None)
    sslmode = query.pop("sslmode", None)
    if sslmode is not None and "ssl" not in query:
        query["ssl"] = sslmode
    return url.set(query=query)


settings = get_settings()
engine = create_async_engine(
    database_url_for_asyncpg(settings.database_url),
    **database_engine_options(settings),
)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
