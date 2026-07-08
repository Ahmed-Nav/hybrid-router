from datetime import datetime, timezone
from database import Tenant, UsageLog
from tests.test_admin_overview import make_admin_token


def test_admin_timeseries_aggregates_across_all_tenants(client, db_session):
    # This endpoint intentionally aggregates across ALL tenants platform-wide (no tenant filter),
    # so other tests running in the same suite may also contribute rows dated "today" to the shared
    # DB. Measure the delta this test itself adds rather than asserting an absolute count.
    t1 = Tenant(id="org_infra_a", api_key="hash_infra_a", plan_tier="BASIC", is_active=True)
    t2 = Tenant(id="org_infra_b", api_key="hash_infra_b", plan_tier="PREMIUM", is_active=True)
    db_session.add_all([t1, t2])
    db_session.commit()

    today = datetime.now(timezone.utc)

    resp_before = client.get("/v1/admin/timeseries?days=7", headers={"Authorization": f"Bearer {make_admin_token()}"})
    bucket_before = next(d for d in resp_before.json()["daily"] if d["date"] == today.strftime("%Y-%m-%d"))

    db_session.add(UsageLog(tenant_id="org_infra_a", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, used_fallback=True, timestamp=today))
    db_session.add(UsageLog(tenant_id="org_infra_b", model_used="gemini", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, used_fallback=False, timestamp=today))
    db_session.commit()

    resp = client.get("/v1/admin/timeseries?days=7", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["daily"]) == 7
    todays_bucket = next(d for d in data["daily"] if d["date"] == today.strftime("%Y-%m-%d"))
    assert todays_bucket["request_count"] - bucket_before["request_count"] == 2
    assert todays_bucket["fallback_count"] - bucket_before["fallback_count"] == 1


def test_admin_timeseries_rejects_non_admin_role(client):
    import jwt
    import os
    from datetime import timedelta
    token = jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": "org_x",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    resp = client.get("/v1/admin/timeseries", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
