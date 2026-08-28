import hashlib
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import get_settings

_fallback: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))


async def enforce_fixed_window_limit(
    request: Request,
    *,
    namespace: str,
    identity: str,
    limit: int,
    unavailable_detail: str,
) -> None:
    settings = get_settings()
    digest = hashlib.sha256(f"{identity}:{request.url.path}".encode()).hexdigest()
    key = f"rate:{namespace}:{digest}"
    try:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.15,
            socket_timeout=0.15,
        )
        async with client:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
    except Exception as error:
        if not settings.is_development:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=unavailable_detail,
            ) from error
        minute = int(datetime.now(UTC).timestamp() // 60)
        stored_minute, stored_count = _fallback[key]
        count = stored_count + 1 if stored_minute == minute else 1
        _fallback[key] = (minute, count)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly",
        )


async def enforce_auth_rate_limit(request: Request) -> None:
    await enforce_fixed_window_limit(
        request,
        namespace="auth",
        identity=request.client.host if request.client else "unknown",
        limit=60,
        unavailable_detail="Authentication is temporarily unavailable",
    )


async def enforce_auth_identity_rate_limit(request: Request, identity: str) -> None:
    await enforce_fixed_window_limit(
        request,
        namespace="auth-account",
        identity=identity.strip().casefold(),
        limit=10,
        unavailable_detail="Authentication is temporarily unavailable",
    )
