import jwt
import os
from datetime import datetime, timedelta, timezone
from database import Tenant, hash_api_key


def _tenant_token(tenant_id):
    return jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_rotate_api_key_returns_new_raw_key_once(client, db_session):
    tenant = Tenant(id="org_rotate_test", api_key=hash_api_key("sk_live_old_raw_key"), plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    resp = client.post(
        "/v1/tenant/api-key/rotate",
        headers={"Authorization": f"Bearer {_tenant_token('org_rotate_test')}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_key"].startswith("sk_live_")
    assert data["api_key"] != "sk_live_old_raw_key"

    db_session.refresh(tenant)
    assert tenant.api_key == hash_api_key(data["api_key"])
    assert tenant.api_key != hash_api_key("sk_live_old_raw_key")


def test_rotate_api_key_rejects_developer_role(client, db_session):
    tenant = Tenant(id="org_rotate_test2", api_key=hash_api_key("sk_live_x"), plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    token = jwt.encode(
        {"sub": "u", "role": "DEVELOPER", "tenant_id": "org_rotate_test2",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    resp = client.post("/v1/tenant/api-key/rotate", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
