import json
import hmac
import hashlib
from fastapi.testclient import TestClient
from database import Tenant, User

def generate_signature(body: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()

def test_webhook_invalid_signature(client: TestClient):
    payload = {"event": "payment.captured"}
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": "invalid_sig"},
        json=payload
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid Razorpay webhook signature."

def test_webhook_payment_captured_success(client: TestClient, db_session):
    secret = "test_razorpay_secret"
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_xyz123",
                    "amount": 199900,  # ₹1,999 (BASIC plan)
                    "currency": "INR",
                    "email": "customer_test@example.com"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode('utf-8')
    sig = generate_signature(body_bytes, secret)

    # Trigger webhook
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig},
        content=body_bytes
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["provisioned_id"] == "org_pay_test_xyz123"
    assert resp.json()["assigned_tier"] == "BASIC"

    # Verify Database records exist
    tenant = db_session.query(Tenant).filter(Tenant.id == "org_pay_test_xyz123").first()
    assert tenant is not None
    assert tenant.plan_tier == "BASIC"
    assert tenant.is_active is True

    user = db_session.query(User).filter(User.tenant_id == "org_pay_test_xyz123").first()
    assert user is not None
    assert user.username == "customer_test@example.com"
    assert user.role == "TENANT_ADMIN"

def test_webhook_payment_failed(client: TestClient, db_session):
    secret = "test_razorpay_secret"
    
    # Pre-provision active tenant & user
    tenant = Tenant(id="org_fail_tenant", api_key="pw_hash", plan_tier="PREMIUM", is_active=True)
    user = User(username="fail_user@example.com", password_hash="pw_hash", role="TENANT_ADMIN", tenant_id="org_fail_tenant")
    db_session.add(tenant)
    db_session.add(user)
    db_session.commit()

    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_123",
                    "email": "fail_user@example.com"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode('utf-8')
    sig = generate_signature(body_bytes, secret)

    # Trigger webhook
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig},
        content=body_bytes
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"

    # Verify database tenant deactivation
    db_session.refresh(tenant)
    assert tenant.is_active is False

def test_webhook_subscription_cancelled(client: TestClient, db_session):
    secret = "test_razorpay_secret"
    
    # Pre-provision active tenant & user
    tenant = Tenant(id="org_cancel_tenant", api_key="pw_hash2", plan_tier="PREMIUM", is_active=True)
    user = User(username="cancel_user@example.com", password_hash="pw_hash2", role="TENANT_ADMIN", tenant_id="org_cancel_tenant")
    db_session.add(tenant)
    db_session.add(user)
    db_session.commit()

    payload = {
        "event": "subscription.cancelled",
        "payload": {
            "subscription": {
                "entity": {
                    "notes": {
                        "email": "cancel_user@example.com"
                    }
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode('utf-8')
    sig = generate_signature(body_bytes, secret)

    # Trigger webhook
    resp = client.post(
        "/v1/webhooks/razorpay",
        headers={"X-Razorpay-Signature": sig},
        content=body_bytes
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"

    # Verify database tenant deactivation
    db_session.refresh(tenant)
    assert tenant.is_active is False
