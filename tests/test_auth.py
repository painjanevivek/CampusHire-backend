from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


async def override_db() -> AsyncIterator[AsyncSession]:
    async with TestSession() as session:
        yield session


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.dependency_overrides[get_db] = override_db
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 204
    token = client.cookies[get_settings().csrf_cookie_name]
    return {"Origin": "http://localhost:3000", "X-CSRF-Token": token}


def signup(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json={"email": "Student@Example.edu", "password": "a long campus passphrase"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_signup_normalizes_email_and_creates_student_session(client: TestClient) -> None:
    payload = signup(client)
    assert payload["email"] == "student@example.edu"
    assert payload["role"] == "student"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == payload["id"]


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    signup(client)
    response = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json={"email": "student@example.edu", "password": "another strong passphrase"},
    )
    assert response.status_code == 409


def test_invalid_credentials_use_generic_error(client: TestClient) -> None:
    signup(client)
    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={"email": "student@example.edu", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_state_change_requires_csrf_and_origin(client: TestClient) -> None:
    signup(client)
    assert client.post("/api/v1/auth/sign-out").status_code == 403


def test_sign_out_revokes_current_session(client: TestClient) -> None:
    signup(client)
    token = client.cookies[get_settings().csrf_cookie_name]
    response = client.post(
        "/api/v1/auth/sign-out",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": token},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
