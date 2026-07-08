import jwt
import os
from datetime import datetime, timedelta, timezone
from database import Tenant, UsageLog


def test_analytics_totals_are_scoped_to_current_month(client, db_session):
    tenant = Tenant(id="org_month_scope_test", api_key="hash_month", plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    now = datetime.now(timezone.utc)
    last_month = (now.replace(day=1) - timedelta(days=1))

    # Old usage from last month — must NOT count toward this month's totals
    db_session.add(UsageLog(
        tenant_id="org_month_scope_test", model_used="llama", prompt_tokens=100, completion_tokens=100,
        cost_incurred=100.0, billed_usage_cost=130.0, reference_cost=200.0, timestamp=last_month,
    ))
    # This month's usage — must count
    db_session.add(UsageLog(
        tenant_id="org_month_scope_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
        cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, timestamp=now,
    ))
    db_session.commit()

    token = jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": "org_month_scope_test",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    resp = client.get("/v1/analytics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_spend"] == 1.3
    assert data["total_reference_cost"] == 2.0
    assert data["total_requests"] == 1
