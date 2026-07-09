from database import Tenant, User, hash_password


def _login(client, username, password):
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


def test_performance_mode_rejected_for_basic_tenant(client, db_session):
    tenant = Tenant(id="org_basic_perf_test", api_key="hash_basic_perf", plan_tier="BASIC",
                     routing_mode="SMART", fallback_provider="groq", is_active=True)
    user = User(username="basic_admin", password_hash=hash_password("pass123"), role="TENANT_ADMIN",
                tenant_id="org_basic_perf_test")
    db_session.add_all([tenant, user])
    db_session.commit()

    token = _login(client, "basic_admin", "pass123")
    resp = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_mode": "PERFORMANCE"},
    )
    assert resp.status_code == 402

    db_session.refresh(tenant)
    assert tenant.routing_mode == "SMART"


def test_performance_mode_allowed_for_premium_tenant(client, db_session):
    tenant = Tenant(id="org_premium_perf_test", api_key="hash_premium_perf", plan_tier="PREMIUM",
                     routing_mode="SMART", fallback_provider="groq", is_active=True)
    user = User(username="premium_admin", password_hash=hash_password("pass123"), role="TENANT_ADMIN",
                tenant_id="org_premium_perf_test")
    db_session.add_all([tenant, user])
    db_session.commit()

    token = _login(client, "premium_admin", "pass123")
    resp = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_mode": "PERFORMANCE"},
    )
    assert resp.status_code == 200
    assert resp.json()["routing_mode"] == "PERFORMANCE"


def test_developer_role_rejected_from_settings_update(client, db_session):
    tenant = Tenant(id="org_dev_settings_test", api_key="hash_dev_settings", plan_tier="PREMIUM",
                     routing_mode="SMART", fallback_provider="groq", is_active=True)
    user = User(username="dev_settings_user", password_hash=hash_password("pass123"), role="DEVELOPER",
                tenant_id="org_dev_settings_test")
    db_session.add_all([tenant, user])
    db_session.commit()

    token = _login(client, "dev_settings_user", "pass123")
    resp = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_mode": "ECO"},
    )
    assert resp.status_code == 403
