from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import rate_limit
from app.core.config import Settings
from app.core.database import database_engine_options
from app.models.auth import Session as AuthSession
from app.models.auth import User, UserRole
from app.models.base import Base
from app.modules.auth import security
from app.modules.auth.dependencies import get_current_session


def test_api_database_pool_is_small_and_bounded() -> None:
    settings = Settings(
        process_role="api",
        database_pool_size=4,
        database_max_overflow=6,
        database_pool_timeout_seconds=8,
        database_pool_recycle_seconds=240,
    )

    assert database_engine_options(settings) == {
        "pool_size": 4,
        "max_overflow": 6,
        "pool_timeout": 8.0,
        "pool_recycle": 240,
        "pool_pre_ping": True,
    }


async def test_password_hashing_and_verification_are_offloaded(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(function: object, *args: object) -> object:
        calls.append((function, args))
        return "hashed" if function is security.hash_password else True

    monkeypatch.setattr(security.asyncio, "to_thread", fake_to_thread)

    assert await security.hash_password_async("correct horse battery staple") == "hashed"
    assert await security.verify_password_async("stored-hash", "candidate") is True
    assert calls == [
        (security.hash_password, ("correct horse battery staple",)),
        (security.verify_password, ("stored-hash", "candidate")),
    ]


class CountingRedis:
    created = 0

    def __init__(self, *_: object, **__: object) -> None:
        type(self).created += 1

    async def incr(self, _: str) -> int:
        return 1

    async def expire(self, _: str, __: int) -> None:
        return None


class CountingPool:
    last_kwargs: dict[str, object] = {}

    @classmethod
    def from_url(cls, *_: object, **kwargs: object) -> "CountingPool":
        cls.last_kwargs = kwargs
        return cls()


def request_for(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
            "app": SimpleNamespace(state=SimpleNamespace()),
        }
    )


async def test_rate_limiter_reuses_one_client_per_application(
    monkeypatch: Any,
) -> None:
    CountingRedis.created = 0
    monkeypatch.setattr(rate_limit, "Redis", CountingRedis)
    monkeypatch.setattr(rate_limit, "BlockingConnectionPool", CountingPool)
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            redis_url="redis://cache",
            redis_max_connections=64,
            redis_pool_timeout_seconds=1.0,
            is_development=False,
        ),
    )
    request = request_for("/api/v1/auth/sign-in")

    for identity in ("first@example.edu", "second@example.edu"):
        await rate_limit.enforce_fixed_window_limit(
            request,
            namespace="auth-account",
            identity=identity,
            limit=10,
            unavailable_detail="Authentication is temporarily unavailable",
        )

    assert CountingRedis.created == 1
    assert CountingPool.last_kwargs["max_connections"] == 64
    assert CountingPool.last_kwargs["timeout"] == 1.0


async def test_authenticated_session_lookup_uses_one_database_round_trip() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    token = "session-token"  # noqa: S105 - synthetic test capability
    async with session_factory() as db:
        user = User(
            email="scale-test@example.edu",
            password_hash="not-used",  # noqa: S106 - password verification is not exercised
            role=UserRole.STUDENT.value,
        )
        db.add(user)
        await db.flush()
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash=security.hash_secret(token),
                csrf_hash=security.hash_secret("csrf-token"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                last_activity_at=datetime.now(UTC),
            )
        )
        await db.commit()

    statements: list[str] = []

    def record_statement(
        _: object,
        __: object,
        statement: str,
        ___: object,
        ____: object,
        _____: object,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        async with session_factory() as db:
            loaded = await get_current_session(db, token)
            assert loaded.user.email == "scale-test@example.edu"
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_statement)
        await engine.dispose()

    assert len(statements) == 1
