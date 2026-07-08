import jwt
import os
from datetime import datetime, timedelta, timezone


def make_token(role, tenant_id=None):
    return jwt.encode(
        {"sub": "test_user", "role": role, "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_admin_overview_rejects_non_admin_role(client):
    token = make_token("DEVELOPER")
    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_admin_overview_rejects_missing_token(client):
    resp = client.get("/v1/admin/overview")
    assert resp.status_code == 403


def test_admin_overview_allows_super_admin_role(client):
    token = make_token("SUPER_ADMIN")
    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
