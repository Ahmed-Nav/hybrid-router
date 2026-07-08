from datetime import datetime, timedelta, timezone
from database import Tenant, UsageLog
from tests.test_admin_overview import make_admin_token


def test_admin_tenants_lists_per_tenant_profit(client, db_session):
    tenant = Tenant(id="org_tenant_row_test", api_key="hash_row", plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()
    db_session.add(UsageLog(tenant_id="org_tenant_row_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=5000.0, billed_usage_cost=1000.0, reference_cost=6000.0))
    # Old usage from last month — must NOT count toward this period's revenue/cost/profit
    last_month = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=1))
    db_session.add(UsageLog(tenant_id="org_tenant_row_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=9000.0, billed_usage_cost=2000.0, reference_cost=10000.0, timestamp=last_month))
    db_session.commit()

    resp = client.get("/v1/admin/tenants", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    rows = resp.json()["tenants"]
    row = next(r for r in rows if r["tenant_id"] == "org_tenant_row_test")
    assert row["plan_tier"] == "BASIC"
    assert row["revenue_this_period"] == 1999.0 + 1000.0
    assert row["cogs_this_period"] == 5000.0
    assert row["profit_this_period"] == (1999.0 + 1000.0) - 5000.0
    assert row["profit_this_period"] < 0   # this tenant's real cost (5000) exceeds what they've been billed (2999) — unprofitable


def test_admin_tenants_flags_churn_risk_and_tier_capped_requests(client, db_session):
    # Tenant A: active recently, no capped requests
    active_tenant = Tenant(id="org_active_test", api_key="hash_active", plan_tier="PREMIUM", is_active=True)
    # Tenant B: no usage in 10 days -> churn risk
    stale_tenant = Tenant(id="org_stale_test", api_key="hash_stale", plan_tier="BASIC", is_active=True)
    # Tenant C: never had any usage -> churn risk
    never_active_tenant = Tenant(id="org_never_active_test", api_key="hash_never", plan_tier="BASIC", is_active=True)
    db_session.add_all([active_tenant, stale_tenant, never_active_tenant])
    db_session.commit()

    now = datetime.now(timezone.utc)
    db_session.add(UsageLog(tenant_id="org_active_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, timestamp=now))
    db_session.add(UsageLog(tenant_id="org_stale_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, was_tier_capped=True,
                             timestamp=now - timedelta(days=10)))
    db_session.commit()

    resp = client.get("/v1/admin/tenants", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    rows = {r["tenant_id"]: r for r in resp.json()["tenants"]}

    assert rows["org_active_test"]["churn_risk"] is False
    assert rows["org_stale_test"]["churn_risk"] is True
    assert rows["org_never_active_test"]["churn_risk"] is True
    assert rows["org_stale_test"]["tier_capped_count"] == 1
    assert rows["org_active_test"]["tier_capped_count"] == 0
