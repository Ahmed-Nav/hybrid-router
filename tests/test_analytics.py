from database import UsageLog, Tenant, log_request, REFERENCE_MODEL_COST_PER_1M_TOKENS, USAGE_MARKUP_MULTIPLIER, PLAN_PRICING
from database import provision_new_tenant


def test_log_request_stores_billed_and_reference_cost(db_session):
    provision_new_tenant(db_session, "org_logtest", "BASIC")

    log_request("org_logtest", "llama-3.1-8b-instant", 1000, 500, 0.0001, used_fallback=True)

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest").first()
    assert log is not None
    assert log.used_fallback is True
    assert log.cost_incurred == 0.0001

    expected_reference = (1500 * REFERENCE_MODEL_COST_PER_1M_TOKENS) / 1_000_000
    expected_billed = 0.0001 * USAGE_MARKUP_MULTIPLIER
    assert round(log.reference_cost, 10) == round(expected_reference, 10)
    assert round(log.billed_usage_cost, 10) == round(expected_billed, 10)


def test_log_request_defaults_used_fallback_false(db_session):
    provision_new_tenant(db_session, "org_logtest2", "BASIC")

    log_request("org_logtest2", "llama-3.1-8b-instant", 100, 50, 0.00002)

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest2").first()
    assert log.used_fallback is False


def test_log_request_stores_tier_capped_flag(db_session):
    provision_new_tenant(db_session, "org_logtest3", "BASIC")

    log_request("org_logtest3", "llama-3.1-8b-instant", 100, 50, 0.00002, was_tier_capped=True)

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest3").first()
    assert log.was_tier_capped is True


def test_log_request_defaults_tier_capped_false(db_session):
    provision_new_tenant(db_session, "org_logtest4", "PREMIUM")

    log_request("org_logtest4", "llama-3.3-70b-versatile", 100, 50, 0.0001)

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest4").first()
    assert log.was_tier_capped is False


def test_plan_pricing_matches_live_pricing_page():
    assert PLAN_PRICING["BASIC"]["base_fee"] == 1999.0
    assert PLAN_PRICING["PREMIUM"]["base_fee"] == 6999.0
    assert PLAN_PRICING["BASIC"]["rate_limit"] == "60/minute"
    assert PLAN_PRICING["PREMIUM"]["rate_limit"] == "1000/minute"


def test_analytics_endpoint_returns_billed_cost_not_raw_cost(client, db_session):
    from database import hash_password
    from database import User

    provision_new_tenant(db_session, "org_analytics_tenant", "BASIC")
    user = User(username="analytics_user", password_hash=hash_password("pass"), role="TENANT_ADMIN", tenant_id="org_analytics_tenant")
    db_session.add(user)
    db_session.commit()

    log_request("org_analytics_tenant", "llama-3.1-8b-instant", 1000, 1000, 0.001, used_fallback=True)

    login_resp = client.post("/v1/auth/login", json={"username": "analytics_user", "password": "pass"})
    token = login_resp.json()["access_token"]

    resp = client.get("/v1/analytics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert "monthly_budget_cap" in data
    assert data["monthly_budget_cap"] is None
    assert "total_spend" in data
    assert "total_reference_cost" in data
    assert "base_fee" in data
    assert data["base_fee"] == 1999.0
    assert round(data["total_spend"], 6) == round(0.001 * USAGE_MARKUP_MULTIPLIER, 6)
    assert data["fallback_count"] == 1
    assert data["recent_logs"][0]["used_fallback"] is True
    assert "billed_usage_cost" in data["recent_logs"][0]
    # raw COGS must never be exposed to the client-facing payload
    assert "cost_incurred" not in data["recent_logs"][0]
