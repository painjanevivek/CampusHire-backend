from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings


def database_engine_options(settings: Settings) -> dict[str, Any]:
    """Return connection settings appropriate for the selected process lifetime."""
    if settings.process_role == "api":
        # Vercel API instances are short-lived and scale horizontally. Let the
        # managed PostgreSQL pooler own connection reuse across invocations.
        return {"poolclass": NullPool}
    return {"pool_pre_ping": True}


settings = get_settings()
engine = create_async_engine(settings.database_url, **database_engine_options(settings))
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
