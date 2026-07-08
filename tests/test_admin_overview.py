import jwt
import os
from datetime import datetime, timedelta, timezone
from database import Tenant, UsageLog


def make_admin_token():
    return jwt.encode(
        {"sub": "founder", "role": "SUPER_ADMIN", "tenant_id": None,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_admin_overview_computes_platform_profit(client, db_session):
    t1 = Tenant(id="org_profit_a", api_key="hash_a", plan_tier="BASIC", is_active=True)
    t2 = Tenant(id="org_profit_b", api_key="hash_b", plan_tier="PREMIUM", is_active=True)
    db_session.add_all([t1, t2])
    db_session.commit()

    # Tenant A: billed 26.0, real cost 20.0 -> profitable on usage
    db_session.add(UsageLog(tenant_id="org_profit_a", model_used="llama", prompt_tokens=100, completion_tokens=100,
                             cost_incurred=20.0, billed_usage_cost=26.0, reference_cost=50.0, used_fallback=False))
    # Tenant B: billed 10.0, real cost 15.0 -> a request that lost money on usage alone
    db_session.add(UsageLog(tenant_id="org_profit_b", model_used="gemini", prompt_tokens=100, completion_tokens=100,
                             cost_incurred=15.0, billed_usage_cost=10.0, reference_cost=40.0, used_fallback=True))
    # Old usage from last month — must NOT count toward this period's platform totals
    last_month = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=1))
    db_session.add(UsageLog(tenant_id="org_profit_a", model_used="llama", prompt_tokens=100, completion_tokens=100,
                             cost_incurred=500.0, billed_usage_cost=650.0, reference_cost=900.0, used_fallback=True,
                             timestamp=last_month))
    db_session.commit()

    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_revenue"] == 1999.0 + 6999.0 + 26.0 + 10.0
    assert data["total_cogs"] == 20.0 + 15.0
    assert data["platform_profit"] == data["total_revenue"] - data["total_cogs"]
    assert data["total_reference_cost_saved"] == 50.0 + 40.0 - (26.0 + 10.0)
    assert data["active_tenant_count"] == 2
    assert data["total_tenant_count"] == 2
    assert data["fallback_trigger_count"] == 1
