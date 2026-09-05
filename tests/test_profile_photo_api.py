from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import Institution, Session, User
from app.models.profile import StudentProfile
from app.modules.auth.security import hash_secret

engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db() -> AsyncIterator[AsyncSession]:
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def login(client: TestClient, role: str = "student") -> tuple[User, dict[str, str]]:
    token, csrf = str(uuid4()), str(uuid4())
    async with TestSession() as db:
        institution = Institution(name="Synthetic college", code=uuid4().hex)
        db.add(institution)
        await db.flush()
        user = User(
            email=f"{uuid4()}@example.edu",
            password_hash=hash_secret(str(uuid4())),
            role=role,
            institution_id=institution.id,
        )
        db.add(user)
        await db.flush()
        db.add(
            Session(
                user_id=user.id,
                token_hash=hash_secret(token),
                csrf_hash=hash_secret(csrf),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                last_activity_at=datetime.now(UTC),
                mfa_verified_at=datetime.now(UTC),
            )
        )
        await db.commit()
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, token)
    client.cookies.set(settings.csrf_cookie_name, csrf)
    return user, {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}


def photo() -> tuple[str, bytes, str]:
    output = BytesIO()
    Image.new("RGB", (32, 32), "blue").save(output, format="PNG")
    return "photo.png", output.getvalue(), "image/png"


async def test_photo_persists_replaces_removes_and_preserves_profile(client: TestClient) -> None:
    user, headers = await login(client)
    async with TestSession() as db:
        db.add(
            StudentProfile(
                user_id=user.id,
                institution_id=user.institution_id,
                full_name="Synthetic student",
                revision=7,
            )
        )
        await db.commit()
    assert client.get("/api/v1/profile/photo").json() == {"data_url": None}
    uploaded = client.put("/api/v1/profile/photo", files={"file": photo()}, headers=headers)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data_url"].startswith("data:image/jpeg;base64,")
    assert uploaded.headers["cache-control"] == "private, no-store"
    assert client.get("/api/v1/profile/photo").json() == uploaded.json()
    assert (
        client.put("/api/v1/profile/photo", files={"file": photo()}, headers=headers).status_code
        == 200
    )
    assert client.get("/api/v1/profile").json()["revision"] == 7
    invalid = client.put(
        "/api/v1/profile/photo", files={"file": ("x.png", b"bad", "image/png")}, headers=headers
    )
    assert invalid.status_code == 422
    assert client.get("/api/v1/profile/photo").json() == uploaded.json()
    assert client.delete("/api/v1/profile/photo", headers=headers).status_code == 204
    assert client.get("/api/v1/profile/photo").json() == {"data_url": None}


async def test_photo_authorization_csrf_and_body_limit(client: TestClient) -> None:
    assert client.get("/api/v1/profile/photo").status_code == 401
    _, headers = await login(client)
    assert client.put("/api/v1/profile/photo", files={"file": photo()}).status_code == 403
    assert (
        client.put("/api/v1/profile/photo", files={"file": photo()}, headers=headers).status_code
        == 200
    )
    owner_cookies = dict(client.cookies)
    await login(client)  # Different student and institution cannot see or remove owner's image.
    assert client.get("/api/v1/profile/photo").json() == {"data_url": None}
    client.cookies.clear()
    client.cookies.update(owner_cookies)
    assert client.get("/api/v1/profile/photo").json()["data_url"] is not None
    too_large = client.put(
        "/api/v1/profile/photo", content=b"x" * (3 * 1024 * 1024), headers=headers
    )
    assert too_large.status_code == 413
    await login(client, "tnp_admin")
    assert client.get("/api/v1/profile/photo").status_code == 403
