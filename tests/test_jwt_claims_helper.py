import jwt
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
import pytest
import main


def _make_token(role="TENANT_ADMIN", tenant_id="org_x"):
    return jwt.encode(
        {"sub": "u", "role": role, "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


class FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def test_decode_bearer_jwt_returns_claims_for_valid_token():
    token = _make_token(role="DEVELOPER")
    claims = main.decode_bearer_jwt(FakeRequest({"Authorization": f"Bearer {token}"}))
    assert claims is not None
    assert claims["role"] == "DEVELOPER"


def test_decode_bearer_jwt_returns_none_for_missing_header():
    assert main.decode_bearer_jwt(FakeRequest({})) is None


def test_decode_bearer_jwt_returns_none_for_invalid_token():
    assert main.decode_bearer_jwt(FakeRequest({"Authorization": "Bearer not-a-real-token"})) is None


def test_get_jwt_claims_raises_403_for_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        main.get_jwt_claims(FakeRequest({}))
    assert exc_info.value.status_code == 403


def test_get_jwt_claims_raises_403_for_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        main.get_jwt_claims(FakeRequest({"Authorization": "Bearer garbage"}))
    assert exc_info.value.status_code == 403


def test_get_jwt_claims_returns_claims_for_valid_token():
    token = _make_token(role="SUPER_ADMIN")
    claims = main.get_jwt_claims(FakeRequest({"Authorization": f"Bearer {token}"}))
    assert claims["role"] == "SUPER_ADMIN"
