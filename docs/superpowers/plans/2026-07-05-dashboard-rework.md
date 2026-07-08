# Dashboard Rework — Master Plan

> **For agentic workers:** This is a master/roadmap plan covering four linked phases. Each phase is its own sub-project — do NOT execute this document directly task-by-task. Before starting a phase, expand that phase into a full TDD plan (file paths, failing tests, code, commit steps) using **superpowers:writing-plans**, then execute it with **superpowers:subagent-driven-development** or **superpowers:executing-plans**. This document exists to lock in scope, sequencing, and the data model changes that later phases depend on.

**Goal:** Turn the dashboard from a routing-control-panel with invented jargon into the actual product — the accountability layer that proves Hybrid Router is saving money and staying reliable, for both paying tenants and the founder.

**Architecture:** No framework change. Same FastAPI + SQLAlchemy backend (`main.py`, `database.py`), same Next.js dashboard (`frontend/src/app/dashboard/page.tsx`). The rework is (a) new backend fields/endpoints to support real numbers instead of frontend-invented constants, (b) a new information architecture and Overview screen per role, (c) a founder/platform view that currently doesn't exist. Existing auth, tenant, and usage-log tables are extended, not replaced.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite/Postgres (via `DATABASE_URL`), Next.js (App Router), Tailwind, `pytest` for backend tests.

---

## Why this order

Phase 0 must come first because Phases 1–3 all display numbers (savings baseline, trend, failover count, platform revenue) that don't exist in the schema yet — building the UI first would mean building it against fake data twice. Phase 1 (IA + Overview) is the highest-visible, lowest-risk win and fixes the outright bug (SUPER_ADMIN blank tabs). Phase 2 is the client-value layer. Phase 3 is the founder cockpit. Phase 4 is cleanup/polish, deliberately last so it isn't wasted on screens that get restructured in Phases 1–3.

---

## Phase 0 — Backend data model & analytics foundation

**Why:** Today, "savings" is computed in the frontend with a hardcoded constant (`estimatedUnroutedCost = totalTokens * 0.79 / 1_000_000` in `page.tsx:130`). That number is unexplained and unverifiable — it must move server-side, tied to real reference pricing, or the whole "proof of savings" pitch stays fake. Similarly there's no way today to know if a request went through the fallback provider, no time-series data for trend/forecast, and no cross-tenant rollup for the founder view.

**Billing model decision (confirmed with founder in planning discussion):** Model B — flat monthly plan fee **plus** a usage markup, not a flat-fee-only or pure-usage-only model. This matters because a flat-fee-only model has no way to stay profitable against heavy users (cost scales with usage, revenue doesn't), which was the actual root of the "am I profitable" confusion.

- **Base fee** (the ₹1,999 / ₹6,999 already on the pricing page) buys **the lane, not unlimited usage**: rate limit tier (`main.py:28-41`, already 60/min vs 1000/min today) and model-tier eligibility (`main.py:499-509`, already gates access to complex-reasoning models behind PREMIUM today). Both of these already exist in the code — Phase 0 doesn't invent new gating, it just makes the existing gating explainable and priced.
- **Usage charge** = real per-request provider cost (`cost_incurred`, already computed correctly in `main.py:554/559`) **× a markup multiplier**, billed to the client. This is new — today `cost_incurred` is the raw, un-marked-up provider cost, and it is currently the number shown to the client as "their spend," which is actually *your* cost, not their bill.
- Three distinct cost numbers must exist per request going forward, not one: `cost_incurred` (raw COGS — founder-only, never shown to the client), `billed_usage_cost` (COGS × markup — what the client actually owes, shown to the client as their usage bill), `reference_cost` (what an unrouted direct call to the top-tier model would've cost — shown to the client only as the savings comparison, never as a bill).

**Files:**
- Modify: `database.py` — extend `Tenant`, `UsageLog` models
- Modify: `main.py:576` (`/v1/analytics`) — return richer payload
- Create: `main.py` new routes — `/v1/analytics/timeseries`, `/v1/admin/overview`, `/v1/admin/tenants`
- Test: `tests/test_analytics.py`, `tests/test_admin.py` (new)

**Schema additions:**
```python
# database.py — Tenant
monthly_budget_cap = Column(Float, nullable=True)   # None = no cap
budget_alert_sent_at = Column(DateTime, nullable=True)

# database.py — UsageLog
used_fallback = Column(Boolean, default=False)      # True if fallback_provider handled this request
reference_cost = Column(Float, default=0.0)         # what this request would've cost on the top-tier model — client-facing savings baseline
billed_usage_cost = Column(Float, default=0.0)      # cost_incurred x markup — what the client actually owes for this request's usage
```
`cost_incurred` (existing column) stays as-is and becomes founder-only data — it is the raw provider cost (COGS), never shown to the client from this point forward.

**Pricing constants (server-side, single source of truth — replaces both the frontend's invented savings constant and the marketing page's disconnected ₹1,999/₹6,999):**
```python
# database.py, module level
REFERENCE_MODEL_COST_PER_1M_TOKENS = 0.79   # cost if every request had gone to the top-tier/reasoning model unrouted — savings baseline
USAGE_MARKUP_MULTIPLIER = 1.3               # client is billed cost_incurred x this; the markup IS the founder's usage-based margin

PLAN_PRICING = {
    "BASIC":   {"base_fee": 1999.0, "rate_limit": "60/minute"},
    "PREMIUM": {"base_fee": 6999.0, "rate_limit": "1000/minute"},
}
```
`PLAN_PRICING` base fees confirmed accurate by founder (2026-07-06) — matches the live pricing page (`frontend/src/app/page.tsx:157,177`), no further check needed before hardcoding. `rate_limit` here documents the existing gate in `main.py:28-41`, it does not change it — Phase 0 centralizes the number, it doesn't move the enforcement.

**`log_request` signature change (`database.py:78`):**
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
`billed_usage_cost` is computed and stored once, at write time, from whatever `USAGE_MARKUP_MULTIPLIER` is in effect that day — so historical bills stay accurate even if the markup is tuned later. Never recompute it retroactively from the current constant.

Callers of `log_request` in `main.py` (around the `/v1/chat/completions` handler, `main.py:466`) need `used_fallback` threaded through from whichever branch actually used `tenant.fallback_provider` — resolve exact call sites in the detailed Phase 0 plan.

**New endpoints to design in the detailed plan (roadmap level, not full code here):**
- `GET /v1/analytics/timeseries?days=30` — tenant-scoped daily spend, tokens, request count, fallback count. Powers the trend chart and "at this rate you'll hit ₹X this month" forecast in Phase 2. "Spend" here means `billed_usage_cost`, not `cost_incurred` — the client never sees raw COGS.
- `GET /v1/analytics` (modify existing, `main.py:576`) — client-facing response switches its cost fields from `cost_incurred` to `billed_usage_cost`, and adds the plan's `base_fee` (from `PLAN_PRICING`) so the dashboard can show "₹1,999 base + ₹X usage = ₹Y total this month."
- `GET /v1/admin/overview` — SUPER_ADMIN only. Platform-wide rollup: total tenant count, active tenants (usage in last 7 days), total revenue collected (sum of active tenants' `base_fee` + sum of `billed_usage_cost` this month), total COGS (sum of `cost_incurred`), **platform profit = revenue − COGS**, aggregate reference cost saved (client-facing savings proof, aggregated), fallback-trigger count platform-wide.
- `GET /v1/admin/tenants` — SUPER_ADMIN only. Per-tenant row: id, plan tier, revenue this month (base fee + billed usage), COGS this month, **profit this month**, last active timestamp, budget cap status. This is what lets the founder spot an unprofitable client — e.g. a Basic-tier account whose `cost_incurred` this month already exceeds ₹1,999 + their usage markup.
- `PATCH /v1/tenant/settings` (extend existing, `main.py:619`) — accept `monthly_budget_cap`.

**Acceptance for Phase 0 (checked in the detailed plan with real pytest cases):**
- `log_request` persists `used_fallback`, `reference_cost`, and `billed_usage_cost` correctly for both eco/smart/performance paths.
- `/v1/analytics` returns `billed_usage_cost`-based totals (not raw `cost_incurred`) plus the plan's `base_fee`, and a `total_reference_cost` aggregate (replacing the frontend's invented estimate).
- `/v1/analytics/timeseries` returns daily buckets, zero-filled for days with no usage (needed so the frontend chart doesn't show gaps as "no data" vs "no spend").
- `/v1/admin/overview` and `/v1/admin/tenants` are 403 for non-SUPER_ADMIN roles, and each tenant's profit figure equals `(base_fee + billed_usage_cost) - cost_incurred` for that period, verified against a seeded tenant with known usage.

---

## Phase 1 — Information architecture rework + Overview screens

**Why:** This is where the confusion actually gets fixed. Two concrete defects plus a full relabeling pass.

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx` (split — see below)
- Create: `frontend/src/app/dashboard/tabs/Overview.tsx`, `Billing.tsx`, `Routing.tsx`, `ApiKeys.tsx`, `IntegrationDocs.tsx`, `UsageStream.tsx`, `Security.tsx`, `AdminOverview.tsx`, `AdminTenants.tsx`, `AdminInfra.tsx` (component split — the 518-line single file is already unwieldy; each tab becomes its own component, per "files that change together live together")

**Bug fixes (do these first — they currently make the SUPER_ADMIN role and dev API key flow non-functional):**
1. SUPER_ADMIN tabs (`Global Platform Analytics`, `B2B Tenant Provisioning`, `Infrastructure Controls`) render nothing today — `page.tsx` has no matching JSX block for any of the three (confirmed by grep — zero matches for those strings outside `getTabs()`). Build `AdminOverview.tsx`, `AdminTenants.tsx`, `AdminInfra.tsx` backed by the Phase 0 `/v1/admin/*` endpoints.
2. API key is permanently masked (`sk_live_************************`, `page.tsx:326`) with no reveal/copy — developers integrating the code snippets below it have no real key to use. The raw key is only ever returned once, at creation, by `provision_new_tenant` (`database.py:95`) — the stored value is a one-way hash, so it cannot be "revealed" later as-is. Resolve in the detailed plan whether to (a) support key rotation with one-time re-reveal, or (b) show the raw key once at signup and rely on rotation for recovery.

**Relabeling (apply verbatim in component names and copy):**

| Old label | New label |
|---|---|
| Control Console | Hybrid Router |
| Clearance | Role |
| GLOBAL_CLUSTER | (tenant name, or "All Tenants" for admin) |
| Module Workspace: {tab} | {tab} (drop the redundant prefix) |
| FinOps Billing Suite | Billing |
| Corporate Expenditure Matrix | Spend Summary |
| The LLM Option Control | Routing |
| Dynamic Routing Preference Controller | Routing Mode |
| Failover Engine Backup Provider | Backup Provider |
| API Key Lifecycle Engine | API Keys |
| Developer Credential Safe | API Key |
| Integration Snippets | Docs & Code Samples |
| Personal Usage Stream | Usage |
| Global Platform Analytics | Platform Overview |
| B2B Tenant Provisioning | Tenants |
| Infrastructure Controls | Infrastructure |

**New tab order per role (Overview always first/default):**
- SUPER_ADMIN: Platform Overview → Tenants → Infrastructure → Security
- TENANT_ADMIN: Overview → Billing → Routing → API Keys → Security
- DEVELOPER: Overview → API Key → Docs & Code Samples → Usage → Security

**Overview.tsx content (tenant-facing — the single most important screen in this rework):**
- Headline bill breakdown, in plain language: "Base plan (Basic): ₹1,999 + Usage this month: ₹X = ₹Y total." Never shows raw `cost_incurred` (COGS) — only `billed_usage_cost`.
- Savings proof, separately: "You saved ₹Z this month vs. calling premium models directly for everything," computed from `total_reference_cost - billed_usage_cost`, with one line explaining the baseline: "Savings = what you'd have paid if every request used our top-tier reference model, compared to what we actually billed you."
- Reliability line: "{fallback_count} requests were automatically failed over to your backup provider — zero downtime for you." (0 is a fine, reassuring state, not an empty state.)
- Current routing mode + one-line consequence ("SMART — balances cost and quality automatically").
- Link-through to Billing/Usage for detail, not the detail itself.

**AdminOverview.tsx content (founder-facing):**
- Revenue this month (sum of base fees + billed usage across all tenants), COGS this month (sum of raw `cost_incurred`), **profit this month** (revenue − COGS) — the number that answers "am I actually making money."
- Aggregate reference-cost saved for clients (proof the product works at portfolio level, useful for your own marketing/investor claims — distinct from your profit).
- Active tenant count vs total, fallback-trigger count platform-wide (infra health signal).
- Flag for any tenant whose `cost_incurred` this month exceeds what they've been billed (`base_fee + billed_usage_cost`) — an early warning that a specific client is unprofitable, linking through to the Tenants tab (Phase 3) for detail.

**Acceptance for Phase 1:**
- Every role, every tab renders content — no blank tab bug survives.
- Overview is the default `activeTab` on load for all three roles.
- No jargon labels from the "old label" column appear anywhere in the rendered UI (grep for them post-implementation).

---

## Phase 2 — Client value features (proof, forecasting, control)

**Why:** Phase 1 makes the existing data honest and visible. Phase 2 adds what a budget-owner asks for before renewing: trend over time, a forecast, and a way to cap spend without filing an engineering ticket.

**Files:**
- Modify: `frontend/src/app/dashboard/tabs/Billing.tsx` (from Phase 1)
- Create: `frontend/src/app/dashboard/components/SpendTrendChart.tsx`
- Modify: `main.py` — budget cap check in the `/v1/chat/completions` request path (`main.py:466`)

**Scope:**
- Spend Summary gets a 30-day trend chart (daily spend vs daily reference cost, so the savings gap is visible over time, not just as a lifetime total) — backed by `/v1/analytics/timeseries` from Phase 0.
- Simple linear forecast: "At this month's rate, you'll spend ~₹X by month end" — a mean-daily-rate projection computed client-side from the timeseries data, no ML needed.
- Budget cap UI: input + save (`PATCH /v1/tenant/settings` with `monthly_budget_cap`), plus a warning banner on Overview when current spend crosses 80%/100% of cap.
- Backend: when `monthly_budget_cap` is set and exceeded, decide enforcement behavior in the detailed plan (hard block vs alert-only) — recommend alert-only for v1 to avoid cutting off a paying client's production traffic on a false positive.

**Acceptance for Phase 2:**
- Trend chart renders with real timeseries data, including zero-spend days.
- Forecast number updates as new usage lands.
- Setting a budget cap persists and the 80%/100% banner appears/disappears correctly against live spend.

---

## Phase 3 — Founder platform cockpit

**Why:** Right now there's no operational view of the business inside the product itself.

**Files:**
- Modify: `frontend/src/app/dashboard/tabs/AdminTenants.tsx`, `AdminInfra.tsx` (scaffolded in Phase 1, fleshed out here)

**Scope:**
- Tenants tab: table of all tenants — plan tier, revenue this month (base fee + billed usage), COGS this month, profit this month, last-active timestamp, budget-cap status — backed by `/v1/admin/tenants`. Sort/flag by profit ascending so unprofitable clients surface first, not just alphabetically. Highlight churn-risk (no usage in 7+ days) and upsell signal (repeatedly near plan ceiling).
- Infrastructure tab: platform-wide fallback-trigger rate over time (is a provider destabilizing), request volume. Error-rate tracking depends on whether failed requests are logged anywhere today — verify during the detailed plan; if not, that's a small Phase 0 addendum, not new scope here.

**Acceptance for Phase 3:**
- Tenant list matches actual DB state for a multi-tenant seed (use `seed.py` to create 3+ tenants with varied usage patterns and verify against the rendered table).

---

## Phase 4 — Polish

**Why:** Deliberately last — no point polishing screens that Phases 1–3 restructure.

**Scope (small, mechanical, no schema changes):**
- Currency: only add a `currency` column to `Tenant` if a non-INR tenant actually exists — confirm with founder before adding, otherwise YAGNI.
- Consistent empty states across all tabs (the existing "no logs yet" pattern in `page.tsx:397` is good — replicate it, don't reinvent per tab).
- Remove leftover flavor-text copy that survives Phase 1's tab-label relabeling (e.g. "Cryptographic footprint..." body copy inside the API Keys tab, `page.tsx:307` — that string is body text, not a tab label, so it isn't covered by the relabeling table and needs a separate pass).

---

## Explicitly out of scope for this rework (called out now to prevent scope creep mid-build)

- Multi-seat / team member invites — not built here; don't design UI copy that implies it exists yet.
- Per-application/per-consumer spend breakdown within a tenant — would need a new `app_label` dimension on `UsageLog` and an API-key-per-app model. Real feature, separate spec, not folded into this rework.
- SSO / audit export / compliance features — flagged as a possible future requirement, not part of this pass.

---

## Next step

Pick which phase to expand into a full execution-ready TDD plan first. Recommended order is Phase 0 → 1 → 2 → 3 → 4, since Phases 1–3 depend on Phase 0's schema/endpoints for real numbers. If the visible IA fix (jargon relabeling + the SUPER_ADMIN blank-tab bug) needs to ship fastest, those specific Phase 1 sub-tasks have no hard dependency on Phase 0 and can be pulled forward — only the Overview screens' *real numbers* wait on Phase 0.
