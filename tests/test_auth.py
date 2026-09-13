from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.core.auth import get_current_identity
from app.core.config import Settings
from app.db.models import ChatRequest


JWT_KEY = "test-secret-key-for-volta-jwt-validation-32-bytes"
USER_ID = "550e8400-e29b-41d4-a716-446655440002"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440001"


class FakeIdentityRepository:
    def __init__(self, identity: dict | None):
        self.identity = identity
        self.lookup_email = None

    def get_user_identity_by_email(self, email: str):
        self.lookup_email = email
        return self.identity


def _settings(secret: str | None = JWT_KEY) -> Settings:
    return Settings(_env_file=None, jwt_key=SecretStr(secret) if secret else None)


def _token(secret: str = JWT_KEY, **claims) -> str:
    payload = {
        "sub": "funcionario@volta.com",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=10),
        **claims,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_identity_comes_from_signed_api_jwt_and_current_database_record() -> None:
    repository = FakeIdentityRepository({"tenant_id": TENANT_ID, "user_id": USER_ID})

    identity = get_current_identity(f"Bearer {_token()}", _settings(), repository)

    assert identity.tenant_id == TENANT_ID
    assert identity.user_id == USER_ID
    assert repository.lookup_email == "funcionario@volta.com"


def test_identity_rejects_missing_bearer_token() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_identity(None, _settings(), FakeIdentityRepository(None))

    assert exc.value.status_code == 401


def test_identity_rejects_wrong_signature() -> None:
    repository = FakeIdentityRepository({"tenant_id": TENANT_ID, "user_id": USER_ID})

    with pytest.raises(HTTPException) as exc:
        get_current_identity(
            f"Bearer {_token(secret='another-secret-key-that-is-long-enough')}",
            _settings(),
            repository,
        )

    assert exc.value.status_code == 401
    assert repository.lookup_email is None


def test_identity_rejects_missing_jwt_key() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_identity(f"Bearer {_token()}", _settings(None), FakeIdentityRepository(None))

    assert exc.value.status_code == 503


def test_identity_rejects_expired_token() -> None:
    token = _token(exp=datetime.now(UTC) - timedelta(seconds=1))

    with pytest.raises(HTTPException) as exc:
        get_current_identity(f"Bearer {token}", _settings(), FakeIdentityRepository(None))

    assert exc.value.status_code == 401


def test_identity_rejects_user_missing_from_database() -> None:
    repository = FakeIdentityRepository(None)

    with pytest.raises(HTTPException) as exc:
        get_current_identity(f"Bearer {_token()}", _settings(), repository)

    assert exc.value.status_code == 401
    assert repository.lookup_email == "funcionario@volta.com"


def test_chat_payload_cannot_set_tenant_or_user_identity() -> None:
    payload = ChatRequest(
        session_id="session-1",
        message="oi",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
    )

    assert "tenant_id" not in payload.model_dump()
    assert "user_id" not in payload.model_dump()
