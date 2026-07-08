import pytest
from database import Tenant, User, hash_password
from fastapi.testclient import TestClient

def test_root_status_check(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"

def test_login_flow(client: TestClient, db_session):
    # Seed a test tenant and user operator
    hashed_pw = hash_password("secretpass123")
    user = User(
        username="testoperator",
        password_hash=hashed_pw,
        role="DEVELOPER",
        tenant_id="org_test_tenant"
    )
    db_session.add(user)
    db_session.commit()

    # Test login failure
    resp_fail = client.post("/v1/auth/login", json={"username": "testoperator", "password": "wrongpassword"})
    assert resp_fail.status_code == 401

    # Test login success
    resp_success = client.post("/v1/auth/login", json={"username": "testoperator", "password": "secretpass123"})
    assert resp_success.status_code == 200
    data = resp_success.json()
    assert data["status"] == "success"
    assert "access_token" in data
    assert data["user_info"]["username"] == "testoperator"

def test_api_key_auth(client: TestClient, db_session):
    # Provision a tenant in database
    from database import provision_new_tenant
    raw_key = provision_new_tenant(db_session, "org_test_auth_tenant", "BASIC")
    
    # Test requests without key (should fail slowapi or auth)
    resp_fail = client.post("/v1/chat/completions", json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": "hi"}]})
    assert resp_fail.status_code == 401

    # Test requests with valid key (should route successfully to inference or fail mock key)
    # Since we don't mock external API keys in provider.py for this basic test, we'll verify it parses header and authenticates tenant.
    resp_auth = client.post(
        "/v1/chat/completions", 
        headers={"X-API-Key": raw_key}, 
        json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": "hi"}]}
    )
    # The API might return 503 if providers aren't initialized, or 200, but not 403 (unauthenticated)
    assert resp_auth.status_code in [200, 503, 402]

def test_tenant_settings_override(client: TestClient, db_session):
    # Setup user session
    hashed_pw = hash_password("pass")
    user = User(
        username="settings_user",
        password_hash=hashed_pw,
        role="TENANT_ADMIN",
        tenant_id="org_settings_tenant"
    )
    tenant = Tenant(
        id="org_settings_tenant",
        api_key="hash",
        plan_tier="PREMIUM",
        routing_mode="SMART",
        fallback_provider="groq"
    )
    db_session.add(user)
    db_session.add(tenant)
    db_session.commit()

    # Login to get token
    login_resp = client.post("/v1/auth/login", json={"username": "settings_user", "password": "pass"})
    token = login_resp.json()["access_token"]

    # PATCH settings
    patch_resp = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_mode": "ECO", "fallback_provider": "gemini"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["routing_mode"] == "ECO"
    assert patch_resp.json()["fallback_provider"] == "gemini"

    # Test validation error
    patch_fail = client.patch(
        "/v1/tenant/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_mode": "INVALID_MODE"}
    )
    assert patch_fail.status_code == 422

def test_change_password(client: TestClient, db_session):
    hashed_pw = hash_password("oldpass123")
    user = User(
        username="pwuser",
        password_hash=hashed_pw,
        role="DEVELOPER",
        tenant_id="org_pw_tenant"
    )
    db_session.add(user)
    db_session.commit()

    # Login to get token
    login_resp = client.post("/v1/auth/login", json={"username": "pwuser", "password": "oldpass123"})
    token = login_resp.json()["access_token"]

    # Change password
    change_resp = client.post(
        "/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "oldpass123", "new_password": "newpassword123"}
    )
    assert change_resp.status_code == 200
    assert change_resp.json()["status"] == "success"

    # Verify new password logins succeed
    login_new = client.post("/v1/auth/login", json={"username": "pwuser", "password": "newpassword123"})
    assert login_new.status_code == 200
