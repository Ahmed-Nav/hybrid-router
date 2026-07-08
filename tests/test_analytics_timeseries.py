import jwt
import os
from datetime import datetime, timedelta, timezone
from database import Tenant, UsageLog


def _tenant_token(tenant_id):
    return jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_timeseries_returns_zero_filled_daily_buckets(client, db_session):
    tenant = Tenant(id="org_timeseries_test", api_key="hash_ts", plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    today = datetime.now(timezone.utc)
    db_session.add(UsageLog(
        tenant_id="org_timeseries_test", model_used="llama", prompt_tokens=100, completion_tokens=100,
        cost_incurred=1.0, billed_usage_cost=1.3, reference_cost=2.0, timestamp=today,
    ))
    db_session.commit()

    resp = client.get(
        "/v1/analytics/timeseries?days=7",
        headers={"Authorization": f"Bearer {_tenant_token('org_timeseries_test')}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["daily"]) == 7
    todays_bucket = next(d for d in data["daily"] if d["date"] == today.strftime("%Y-%m-%d"))
    assert todays_bucket["billed_usage_cost"] == 1.3
    assert todays_bucket["reference_cost"] == 2.0
    assert todays_bucket["request_count"] == 1
    other_days = [d for d in data["daily"] if d["date"] != today.strftime("%Y-%m-%d")]
    assert all(d["billed_usage_cost"] == 0.0 and d["request_count"] == 0 for d in other_days)
