# Phase 0 — Backend Data Model & Analytics Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan implements Phase 0 of `docs/superpowers/plans/2026-07-05-dashboard-rework.md` — read that file first for the "why," this file is the "how."

**Goal:** Make every cost/savings/profit number in the dashboard come from real, stored data instead of frontend-invented constants — and give the founder, for the first time, a real revenue-minus-cost profit figure per tenant and platform-wide.

**Architecture:** Extend the existing `Tenant` and `UsageLog` SQLAlchemy models in `database.py` with new columns (no new tables). Centralize pricing/markup constants in `database.py`. Update `log_request` to compute and store `billed_usage_cost` and `reference_cost` at write time. Update `/v1/analytics` to report client-facing (billed) numbers instead of raw cost. Add a new `/v1/analytics/timeseries` endpoint and two new SUPER_ADMIN-only `/v1/admin/*` endpoints, backed by a new `get_current_admin_user` auth dependency (the existing tenant-lookup dependencies don't work for SUPER_ADMIN, whose `User.tenant_id` is `None`).

**Tech Stack:** FastAPI, SQLAlchemy, SQLite (dev, `./test.db` for tests) / Postgres (prod, via `DATABASE_URL`), `pytest` + `TestClient`, existing `tests/conftest.py` fixtures (`client`, `db_session`).

---

## Important discovery affecting this plan

`database.py:54` runs `Base.metadata.create_all(bind=engine)` at import time. This only creates tables that don't exist yet — it does **not** add new columns to tables that already have rows in a persistent database (production Postgres, or a dev SQLite file that already has data). Task 1 includes a manual `ALTER TABLE` migration step for that reason. Tests use a fresh SQLite file created from scratch each session (`tests/conftest.py:23-32`), so tests will pass without running the migration — but production will not pick up the new columns without it. Do not skip Task 1's migration step when deploying.

Also: `get_tenant_from_session_or_key` (`main.py:219`) resolves a `Tenant` row from the JWT's `tenant_id` claim. SUPER_ADMIN users have `tenant_id = None` (see `database.py:39`, nullable), so this dependency cannot authenticate a SUPER_ADMIN and must not be reused for the new admin endpoints. Task 4 adds a separate `get_current_admin_user` dependency that checks the JWT's `role` claim directly (the JWT already includes `role`, see `main.py:318`).

---

### Task 1: Schema additions + migration

**Files:**
- Modify: `database.py:18-31` (Tenant model), `database.py:44-52` (UsageLog model)
- Create: `migrate_phase0.py` (one-off manual migration script for existing Postgres/SQLite databases)
- Test: `tests/test_schema_migration.py`

- [ ] **Step 1: Write the failing test for new columns existing with correct defaults**

```python
# tests/test_schema_migration.py
from database import Tenant, UsageLog

def test_tenant_has_budget_cap_fields(db_session):
    tenant = Tenant(id="org_schema_test", api_key="hash123", plan_tier="BASIC")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    assert tenant.monthly_budget_cap is None
    assert tenant.budget_alert_sent_at is None

def test_usage_log_has_billing_fields(db_session):
    log = UsageLog(
        tenant_id="org_schema_test",
        model_used="llama-3.3-70b-versatile",
        prompt_tokens=100,
        completion_tokens=50,
        cost_incurred=0.001,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    assert log.used_fallback is False
    assert log.reference_cost == 0.0
    assert log.billed_usage_cost == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema_migration.py -v`
Expected: FAIL with `AttributeError: 'Tenant' object has no attribute 'monthly_budget_cap'` (or equivalent for the other fields)

- [ ] **Step 3: Add the columns**

In `database.py`, inside the `Tenant` class (after `fallback_provider`, before `created_at`):
```python
    monthly_budget_cap = Column(Float, nullable=True)   # None = no cap set
    budget_alert_sent_at = Column(DateTime, nullable=True)
```

Inside the `UsageLog` class (after `cost_incurred`, before `timestamp`):
```python
    used_fallback = Column(Boolean, default=False)
    reference_cost = Column(Float, default=0.0)
    billed_usage_cost = Column(Float, default=0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema_migration.py -v`
Expected: PASS

- [ ] **Step 5: Write the production migration script**

```python
# migrate_phase0.py
"""
One-off manual migration for Phase 0 schema additions.
Run once against the production DATABASE_URL before deploying the Phase 0 backend changes.
Safe to re-run: each ALTER is wrapped so an already-migrated database is a no-op.
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("FATAL: DATABASE_URL environment variable is unset.")

engine = create_engine(DATABASE_URL)

STATEMENTS = [
    "ALTER TABLE tenants ADD COLUMN monthly_budget_cap FLOAT",
    "ALTER TABLE tenants ADD COLUMN budget_alert_sent_at TIMESTAMP",
    "ALTER TABLE usage_logs ADD COLUMN used_fallback BOOLEAN DEFAULT FALSE",
    "ALTER TABLE usage_logs ADD COLUMN reference_cost FLOAT DEFAULT 0.0",
    "ALTER TABLE usage_logs ADD COLUMN billed_usage_cost FLOAT DEFAULT 0.0",
]

with engine.connect() as conn:
    for stmt in STATEMENTS:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f"OK: {stmt}")
        except Exception as e:
            print(f"SKIPPED (likely already applied): {stmt} — {e}")
```

- [ ] **Step 6: Commit**

```bash
git add database.py migrate_phase0.py tests/test_schema_migration.py
git commit -m "feat: add budget cap and billing fields to Tenant/UsageLog schema"
```

---

### Task 2: Centralize pricing constants

**Files:**
- Modify: `database.py` (module level, near the top, after imports)
- Test: `tests/test_pricing_constants.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_constants.py
from database import REFERENCE_MODEL_COST_PER_1M_TOKENS, USAGE_MARKUP_MULTIPLIER, PLAN_PRICING

def test_pricing_constants_exist_and_match_live_pricing_page():
    assert REFERENCE_MODEL_COST_PER_1M_TOKENS == 0.79
    assert USAGE_MARKUP_MULTIPLIER == 1.3
    assert PLAN_PRICING["BASIC"]["base_fee"] == 1999.0
    assert PLAN_PRICING["BASIC"]["rate_limit"] == "60/minute"
    assert PLAN_PRICING["PREMIUM"]["base_fee"] == 6999.0
    assert PLAN_PRICING["PREMIUM"]["rate_limit"] == "1000/minute"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pricing_constants.py -v`
Expected: FAIL with `ImportError: cannot import name 'REFERENCE_MODEL_COST_PER_1M_TOKENS' from 'database'`

- [ ] **Step 3: Add the constants**

In `database.py`, directly below the `DATABASE_URL`/`engine` setup (before the `Base = declarative_base()` line is fine, or right after — keep it near the top so it's easy to find):
```python
REFERENCE_MODEL_COST_PER_1M_TOKENS = 0.79
USAGE_MARKUP_MULTIPLIER = 1.3

PLAN_PRICING = {
    "BASIC":   {"base_fee": 1999.0, "rate_limit": "60/minute"},
    "PREMIUM": {"base_fee": 6999.0, "rate_limit": "1000/minute"},
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pricing_constants.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_pricing_constants.py
git commit -m "feat: centralize plan pricing and markup constants"
```

---

### Task 3: Update `log_request` to compute and store real billing numbers

**Files:**
- Modify: `database.py:78-91` (`log_request` function)
- Modify: `main.py:563` (call site — add `used_fallback` argument)
- Test: `tests/test_log_request.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_log_request.py
import pytest
from database import log_request, UsageLog, REFERENCE_MODEL_COST_PER_1M_TOKENS, USAGE_MARKUP_MULTIPLIER

def test_log_request_computes_billed_and_reference_cost(db_session):
    log_request(
        tenant_id="org_logtest",
        model="llama-3.3-70b-versatile",
        p_tokens=1_000_000,
        c_tokens=0,
        cost=0.59,          # matches main.py's real per-token provider cost calc for this model
        used_fallback=False,
    )
    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest").first()
    assert log is not None
    assert log.cost_incurred == 0.59
    assert log.used_fallback is False
    assert log.reference_cost == pytest.approx(1_000_000 * REFERENCE_MODEL_COST_PER_1M_TOKENS / 1_000_000)
    assert log.billed_usage_cost == pytest.approx(0.59 * USAGE_MARKUP_MULTIPLIER)

def test_log_request_records_fallback_flag(db_session):
    log_request(
        tenant_id="org_logtest2",
        model="gemini-1.5-flash",
        p_tokens=500,
        c_tokens=200,
        cost=0.0002,
        used_fallback=True,
    )
    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_logtest2").first()
    assert log.used_fallback is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_log_request.py -v`
Expected: FAIL with `TypeError: log_request() got an unexpected keyword argument 'used_fallback'`

- [ ] **Step 3: Update `log_request`**

Replace `database.py:78-91`:
```python
def log_request(tenant_id, model, p_tokens, c_tokens, cost, used_fallback=False):
    db = SessionLocal()
    try:
        total_tokens = p_tokens + c_tokens
        reference_cost = (total_tokens * REFERENCE_MODEL_COST_PER_1M_TOKENS) / 1_000_000
        billed_usage_cost = cost * USAGE_MARKUP_MULTIPLIER
        log = UsageLog(
            tenant_id=tenant_id,
            model_used=model,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            cost_incurred=cost,
            used_fallback=used_fallback,
            reference_cost=reference_cost,
            billed_usage_cost=billed_usage_cost,
        )
        db.add(log)
        db.commit()
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_log_request.py -v`
Expected: PASS

- [ ] **Step 5: Thread `used_fallback` through from the actual call site**

In `main.py`, the completions handler already knows whether fallback happened — it compares `actual_provider != planned_provider` at `main.py:539`. Update the `log_request` call at `main.py:563`:

Before:
```python
        background_tasks.add_task(log_request, tenant.id, actual_model, p_tokens, c_tokens, cost)
```

After:
```python
        request_used_fallback = actual_provider != planned_provider
        background_tasks.add_task(log_request, tenant.id, actual_model, p_tokens, c_tokens, cost, request_used_fallback)
```

- [ ] **Step 6: Write a test confirming the API-level fallback flag is recorded**

```python
# tests/test_log_request.py (append)
def test_completions_endpoint_records_fallback_flag(client, db_session, monkeypatch):
    from database import Tenant
    import main

    tenant = Tenant(id="org_fallback_e2e", api_key="hashed_e2e_key", plan_tier="PREMIUM", is_active=True)
    db_session.add(tenant)
    db_session.commit()

    class FakeRouteChoice:
        name = "simple_chat"

    class FakeRouter:
        sr = staticmethod(lambda prompt: FakeRouteChoice())
        MODEL_MAPPINGS = {"simple_chat": {"model": "llama-3.1-8b-instant", "provider": "groq"}}

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5

    class FakeChoiceMsg:
        content = "hello"

    class FakeChoice:
        message = FakeChoiceMsg()

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    async def fake_get_response(model_name, messages, provider, fallback_provider, stream):
        # Simulate the primary provider failing over to the backup provider
        return FakeResponse(), fallback_provider, model_name

    monkeypatch.setattr(main, "router", FakeRouter())
    monkeypatch.setattr(main.inference_manager, "get_response", fake_get_response)
    monkeypatch.setattr(main, "hash_api_key", lambda k: "hashed_e2e_key")

    resp = client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": "raw_e2e_key"},
        json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200

    from database import UsageLog
    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_fallback_e2e").order_by(UsageLog.id.desc()).first()
    assert log is not None
    assert log.used_fallback is True
```

Note: this test mocks `router` and `inference_manager.get_response` because they call real external providers — check `main.py`'s existing imports for the exact `inference_manager` object name before wiring this up; adjust the monkeypatch target if it's imported differently (e.g. `from provider import inference_manager` vs a module-level instance).

- [ ] **Step 7: Run the full test file and verify all pass**

Run: `pytest tests/test_log_request.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add database.py main.py tests/test_log_request.py
git commit -m "feat: compute and store real billed usage cost, reference cost, and fallback flag per request"
```

---

### Task 4: Admin auth dependency

**Files:**
- Modify: `main.py` (near `get_tenant_from_session_or_key`, `main.py:219-248`)
- Test: `tests/test_admin_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_auth.py
import jwt
import os
from datetime import datetime, timedelta, timezone

def make_token(role, tenant_id=None):
    return jwt.encode(
        {"sub": "test_user", "role": role, "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )

def test_admin_overview_rejects_non_admin_role(client):
    token = make_token("DEVELOPER")
    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403

def test_admin_overview_rejects_missing_token(client):
    resp = client.get("/v1/admin/overview")
    assert resp.status_code == 403

def test_admin_overview_allows_super_admin_role(client):
    token = make_token("SUPER_ADMIN")
    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_auth.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the `get_current_admin_user` dependency**

In `main.py`, directly after `get_tenant_from_session_or_key` (after line 248):
```python
async def get_current_admin_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing or invalid authorization header.")
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired session token.")
    if payload.get("role") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="This resource requires platform administrator access.")
    return payload
```

This checks the `role` claim directly from the JWT rather than looking up a `Tenant` row, since SUPER_ADMIN users have no `tenant_id` (`database.py:39`).

- [ ] **Step 4: Add a placeholder route so the auth test can pass (full response body built in Task 5)**

```python
@app.get("/v1/admin/overview")
async def get_admin_overview(admin: dict = Depends(get_current_admin_user)):
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_admin_auth.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_admin_auth.py
git commit -m "feat: add SUPER_ADMIN-only auth dependency for platform admin endpoints"
```

---

### Task 5: `/v1/admin/overview` — platform-wide revenue, cost, profit

**Files:**
- Modify: `main.py` (replace placeholder from Task 4)
- Test: `tests/test_admin_overview.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_overview.py
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
    db_session.commit()

    resp = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    data = resp.json()

    # Revenue = base fees (1999 + 6999) + billed usage (26.0 + 10.0)
    assert data["total_revenue"] == 1999.0 + 6999.0 + 26.0 + 10.0
    # COGS = 20.0 + 15.0
    assert data["total_cogs"] == 20.0 + 15.0
    assert data["platform_profit"] == data["total_revenue"] - data["total_cogs"]
    assert data["total_reference_cost_saved"] == 50.0 + 40.0 - (26.0 + 10.0)
    assert data["active_tenant_count"] == 2
    assert data["total_tenant_count"] == 2
    assert data["fallback_trigger_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_overview.py -v`
Expected: FAIL — placeholder route only returns `{"status": "ok"}`, missing all the expected fields

- [ ] **Step 3: Implement the full endpoint**

Replace the placeholder from Task 4 with:
```python
@app.get("/v1/admin/overview")
async def get_admin_overview(admin: dict = Depends(get_current_admin_user)):
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        total_tenant_count = len(tenants)
        active_tenants = [t for t in tenants if t.is_active]
        active_tenant_count = len(active_tenants)

        total_base_fee_revenue = sum(
            PLAN_PRICING.get(t.plan_tier, {}).get("base_fee", 0.0) for t in active_tenants
        )

        usage_stats = db.query(
            func.sum(UsageLog.billed_usage_cost).label("total_billed"),
            func.sum(UsageLog.cost_incurred).label("total_cogs"),
            func.sum(UsageLog.reference_cost).label("total_reference"),
        ).first()

        total_billed = float(usage_stats.total_billed or 0)
        total_cogs = float(usage_stats.total_cogs or 0)
        total_reference = float(usage_stats.total_reference or 0)

        total_revenue = total_base_fee_revenue + total_billed
        platform_profit = total_revenue - total_cogs

        fallback_trigger_count = db.query(UsageLog).filter(UsageLog.used_fallback == True).count()

        return {
            "total_tenant_count": total_tenant_count,
            "active_tenant_count": active_tenant_count,
            "total_revenue": round(total_revenue, 4),
            "total_cogs": round(total_cogs, 4),
            "platform_profit": round(platform_profit, 4),
            "total_reference_cost_saved": round(total_reference - total_billed, 4),
            "fallback_trigger_count": fallback_trigger_count,
        }
    finally:
        db.close()
```

`PLAN_PRICING` and `func` need to be imported/available in `main.py` — `func` is already imported (used at `main.py:580`); add `PLAN_PRICING` to the existing `from database import ...` line at the top of `main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin_overview.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_admin_overview.py
git commit -m "feat: implement platform-wide revenue, cost, and profit rollup endpoint"
```

---

### Task 6: `/v1/admin/tenants` — per-tenant profit breakdown

**Files:**
- Modify: `main.py`
- Test: `tests/test_admin_tenants.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_tenants.py
from database import Tenant, UsageLog
from tests.test_admin_overview import make_admin_token

def test_admin_tenants_lists_per_tenant_profit(client, db_session):
    tenant = Tenant(id="org_tenant_row_test", api_key="hash_row", plan_tier="BASIC", is_active=True)
    db_session.add(tenant)
    db_session.commit()
    db_session.add(UsageLog(tenant_id="org_tenant_row_test", model_used="llama", prompt_tokens=10, completion_tokens=10,
                             cost_incurred=2500.0, billed_usage_cost=1000.0, reference_cost=3000.0))
    db_session.commit()

    resp = client.get("/v1/admin/tenants", headers={"Authorization": f"Bearer {make_admin_token()}"})
    assert resp.status_code == 200
    rows = resp.json()["tenants"]
    row = next(r for r in rows if r["tenant_id"] == "org_tenant_row_test")
    assert row["plan_tier"] == "BASIC"
    assert row["revenue_this_period"] == 1999.0 + 1000.0
    assert row["cogs_this_period"] == 2500.0
    assert row["profit_this_period"] == (1999.0 + 1000.0) - 2500.0
    assert row["profit_this_period"] < 0   # this tenant is unprofitable — heavy usage on a Basic plan
```

Note: importing `make_admin_token` from another test module works but is a minor smell — if the detailed reviewer flags it, move `make_admin_token` into `tests/conftest.py` as a shared fixture/helper instead.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_tenants.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Implement the endpoint**

```python
@app.get("/v1/admin/tenants")
async def get_admin_tenants(admin: dict = Depends(get_current_admin_user)):
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        rows = []
        for t in tenants:
            usage_stats = db.query(
                func.sum(UsageLog.billed_usage_cost).label("billed"),
                func.sum(UsageLog.cost_incurred).label("cogs"),
                func.max(UsageLog.timestamp).label("last_active"),
            ).filter(UsageLog.tenant_id == t.id).first()

            billed = float(usage_stats.billed or 0)
            cogs = float(usage_stats.cogs or 0)
            base_fee = PLAN_PRICING.get(t.plan_tier, {}).get("base_fee", 0.0)
            revenue = base_fee + billed

            rows.append({
                "tenant_id": t.id,
                "plan_tier": t.plan_tier,
                "is_active": t.is_active,
                "revenue_this_period": round(revenue, 4),
                "cogs_this_period": round(cogs, 4),
                "profit_this_period": round(revenue - cogs, 4),
                "last_active": usage_stats.last_active.isoformat() if usage_stats.last_active else None,
                "monthly_budget_cap": t.monthly_budget_cap,
            })

        rows.sort(key=lambda r: r["profit_this_period"])
        return {"tenants": rows}
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin_tenants.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_admin_tenants.py
git commit -m "feat: add per-tenant profit breakdown endpoint, sorted least-profitable first"
```

---

### Task 7: Update `/v1/analytics` to report billed cost, not raw COGS, plus base fee

**Files:**
- Modify: `main.py:576-611`
- Test: `tests/test_analytics_billing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_billing.py
from database import Tenant, UsageLog

def test_analytics_reports_billed_cost_and_base_fee(client, db_session):
    tenant = Tenant(id="org_analytics_test", api_key="hash_analytics", plan_tier="PREMIUM", is_active=True)
    db_session.add(tenant)
    db_session.commit()
    db_session.add(UsageLog(tenant_id="org_analytics_test", model_used="gemini", prompt_tokens=1000, completion_tokens=500,
                             cost_incurred=5.0, billed_usage_cost=6.5, reference_cost=12.0, used_fallback=True))
    db_session.commit()

    import jwt, os
    from datetime import datetime, timedelta, timezone
    token = jwt.encode(
        {"sub": "u", "role": "TENANT_ADMIN", "tenant_id": "org_analytics_test",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    resp = client.get("/v1/analytics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_spend"] == 6.5          # billed_usage_cost, NOT raw cost_incurred (5.0)
    assert data["base_fee"] == 6999.0          # PREMIUM plan
    assert data["total_reference_cost"] == 12.0
    assert data["fallback_count"] == 1
    assert data["recent_logs"][0]["billed_usage_cost"] == 6.5
    assert "cost_incurred" not in data["recent_logs"][0]   # raw COGS must never reach the client response
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_billing.py -v`
Expected: FAIL — `total_spend` currently equals `cost_incurred` (5.0), `base_fee`/`total_reference_cost`/`fallback_count` keys don't exist, `recent_logs` still exposes `cost_incurred`

- [ ] **Step 3: Update the endpoint**

Replace `main.py:576-611`:
```python
@app.get("/v1/analytics")
async def get_analytics(tenant: Tenant = Depends(get_tenant_from_session_or_key)):
    db = SessionLocal()
    try:
        stats = db.query(
            func.sum(UsageLog.billed_usage_cost).label("total_billed"),
            func.sum(UsageLog.reference_cost).label("total_reference"),
            func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens"),
        ).filter(UsageLog.tenant_id == tenant.id).first()

        total_requests = db.query(UsageLog).filter(UsageLog.tenant_id == tenant.id).count()
        fallback_count = db.query(UsageLog).filter(
            UsageLog.tenant_id == tenant.id, UsageLog.used_fallback == True
        ).count()

        recent_logs_query = db.query(UsageLog).filter(UsageLog.tenant_id == tenant.id).order_by(UsageLog.timestamp.desc()).limit(5).all()
        recent_logs = [
            {
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "model_used": log.model_used,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "billed_usage_cost": round(log.billed_usage_cost, 6) if log.billed_usage_cost else 0.0,
                "used_fallback": log.used_fallback,
            }
            for log in recent_logs_query
        ]

        base_fee = PLAN_PRICING.get(tenant.plan_tier, {}).get("base_fee", 0.0)

        return {
            "tenant_id": tenant.id,
            "plan_tier": tenant.plan_tier,
            "routing_mode": tenant.routing_mode,
            "fallback_provider": tenant.fallback_provider,
            "base_fee": base_fee,
            "total_spend": round(float(stats.total_billed or 0), 4),
            "total_reference_cost": round(float(stats.total_reference or 0), 4),
            "total_tokens": int(stats.total_tokens or 0),
            "total_requests": total_requests,
            "fallback_count": fallback_count,
            "recent_logs": recent_logs,
            "api_key_hash": tenant.api_key,
        }
    finally:
        db.close()
```

Note this is a **breaking response shape change** for the existing frontend (`page.tsx` currently reads `metrics.recent_logs[i].cost_incurred` at `page.tsx:411`, and `metrics.total_tokens`/`total_spend` at `page.tsx:130-131`). The frontend will break until Phase 1 updates it to read `billed_usage_cost` and the new fields — this is expected and intentional, since Phase 1 is the very next phase and rewrites this component anyway. Do not add a backwards-compatibility shim for `cost_incurred` in the response; the whole point of this change is that raw COGS stops being client-visible.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analytics_billing.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: All tests pass across `test_auth.py`, `test_billing.py`, and every new Phase 0 test file.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_analytics_billing.py
git commit -m "feat: report billed usage cost and base fee in analytics, stop exposing raw COGS to clients"
```

---

### Task 8: `/v1/analytics/timeseries` — daily buckets for trend/forecast

**Files:**
- Modify: `main.py` (new route, near `/v1/analytics`)
- Test: `tests/test_analytics_timeseries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_timeseries.py
import jwt, os
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_timeseries.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Implement the endpoint**

```python
@app.get("/v1/analytics/timeseries")
async def get_analytics_timeseries(days: int = 30, tenant: Tenant = Depends(get_tenant_from_session_or_key)):
    db = SessionLocal()
    try:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days - 1)

        logs = db.query(UsageLog).filter(
            UsageLog.tenant_id == tenant.id,
            UsageLog.timestamp >= start_date,
        ).all()

        buckets = {
            (start_date + timedelta(days=i)).isoformat(): {
                "date": (start_date + timedelta(days=i)).isoformat(),
                "billed_usage_cost": 0.0,
                "reference_cost": 0.0,
                "request_count": 0,
                "fallback_count": 0,
            }
            for i in range(days)
        }

        for log in logs:
            key = log.timestamp.date().isoformat()
            if key in buckets:
                buckets[key]["billed_usage_cost"] += log.billed_usage_cost or 0.0
                buckets[key]["reference_cost"] += log.reference_cost or 0.0
                buckets[key]["request_count"] += 1
                if log.used_fallback:
                    buckets[key]["fallback_count"] += 1

        daily = [buckets[k] for k in sorted(buckets.keys())]
        for d in daily:
            d["billed_usage_cost"] = round(d["billed_usage_cost"], 4)
            d["reference_cost"] = round(d["reference_cost"], 4)

        return {"daily": daily}
    finally:
        db.close()
```

`timezone` and `timedelta` are already imported in `main.py` (used at `main.py:315`) — confirm the exact import line before assuming, adjust if only `datetime` is imported without `timezone`/`timedelta` as bare names.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analytics_timeseries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_analytics_timeseries.py
git commit -m "feat: add zero-filled daily timeseries endpoint for trend charts and forecasting"
```

---

### Task 9: Extend `PATCH /v1/tenant/settings` with `monthly_budget_cap`

**Files:**
- Modify: `main.py:95-100` (`TenantSettingsUpdate` model — check exact fields first), `main.py:619-643`
- Test: `tests/test_budget_cap_setting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget_cap_setting.py
import jwt, os
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_budget_cap_setting.py -v`
Expected: FAIL — `monthly_budget_cap` not accepted by the request model / not in the response

- [ ] **Step 3: Update the Pydantic model**

Read `main.py:95-100` first to see the exact current field list of `TenantSettingsUpdate`, then add:
```python
    monthly_budget_cap: Optional[float] = None
```
alongside the existing `routing_mode` / `fallback_provider` fields (keep whatever `Optional` import pattern the file already uses).

- [ ] **Step 4: Update the endpoint**

In `update_tenant_settings` (`main.py:619-643`), add handling alongside the existing `if update.routing_mode:` / `if update.fallback_provider:` blocks:
```python
        if update.monthly_budget_cap is not None:
            tenant_row.monthly_budget_cap = update.monthly_budget_cap
```
and add `"monthly_budget_cap": tenant_row.monthly_budget_cap` to the returned dict.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_budget_cap_setting.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_budget_cap_setting.py
git commit -m "feat: allow tenants to set a monthly budget cap via settings endpoint"
```

---

### Task 10: Full regression pass

- [ ] **Step 1: Run the entire backend test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (existing `test_auth.py`, `test_billing.py`, plus every new Phase 0 test file).

- [ ] **Step 2: Manually verify the migration script against a throwaway copy of the dev database**

Run: `python migrate_phase0.py` against a copy of `test.db` (or a scratch Postgres instance) — confirm it prints `OK:` for each statement with no errors, then confirm re-running it prints `SKIPPED` lines instead of failing hard.

- [ ] **Step 3: Confirm no code outside this plan still reads the old `/v1/analytics` shape**

Run: `grep -rn "cost_incurred" frontend/src` — expect matches only in `frontend/src/app/dashboard/page.tsx` (to be fixed in Phase 1, not this plan) and nowhere else.

---

## Self-review notes (from writing this plan)

- **Spec coverage:** every schema field, endpoint, and acceptance criterion from Phase 0 of the master plan (`2026-07-05-dashboard-rework.md:35-99`) has a corresponding task above (Tasks 1–2 = schema/constants, Task 3 = `log_request`, Tasks 4–6 = admin endpoints + auth, Task 7 = `/v1/analytics` rewrite, Task 8 = timeseries, Task 9 = budget cap PATCH).
- **Known open item carried into execution:** Task 3 Step 6's mock of `inference_manager.get_response` assumes a specific import shape in `main.py` that should be confirmed by reading the actual import lines before writing that step for real — flagged inline rather than guessed silently.
- **Frontend breakage is intentional, not a bug:** Task 7 explicitly breaks the current dashboard's reading of `cost_incurred`/`total_tokens` shape. This is expected — Phase 1 (separate plan) rewrites `page.tsx` immediately after. Do not add compatibility shims here.
