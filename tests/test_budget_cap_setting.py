import jwt
import os
from datetime import datetime, timedelta, timezone
from database import Tenant


def test_set_monthly_budget_cap(client, db_session):
    tenant = Tenant(id="org_budget_test", api_key="hash_budget", plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    token = jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": "org_budget_test",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    resp = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"monthly_budget_cap": 5000.0},
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_budget_cap"] == 5000.0

    db_session.refresh(tenant)
    assert tenant.monthly_budget_cap == 5000.0
