# Codebase Hardening & Cleanup — Master Plan

> **For agentic workers:** This is a master/roadmap plan covering five linked phases, addressing every finding from the 2026-07-08 full-codebase audit. Each phase is its own sub-project — do NOT execute this document directly task-by-task. Before starting a phase, expand it into a full TDD plan (file paths, failing tests, code, commit steps) using **superpowers:writing-plans**, then execute it with **superpowers:subagent-driven-development** or **superpowers:executing-plans**.

**Goal:** Close every security gap, fix every data-integrity bug, and remove the dead code/dependencies found in the full-codebase audit — without destabilizing the dashboard rework (Phases 0–4) that just shipped.

**Architecture:** No framework change. All fixes land in the existing `main.py` / `database.py` / `provider.py` / `sanitizer.py` backend and the existing `frontend/src/app/dashboard/page.tsx` / `frontend/src/app/login/page.tsx`. Two new small shared helpers get extracted (`get_jwt_claims()`, `compute_provider_cost()`) to kill duplicated logic found during the audit.

**Tech Stack:** FastAPI, SQLAlchemy, pytest + `TestClient` (existing `tests/conftest.py` fixtures), Next.js/TypeScript, Presidio/spaCy.

---

## Why this order

Phase A goes first because it closes real authorization/security gaps — a Basic tenant saving a setting that lies to them, and a settings endpoint any logged-in role can call regardless of permission, are both active issues right now, not theoretical. Phase B fixes data-integrity bugs (the streaming billing gap silently undercounts the exact numbers Phase 0/3 of the dashboard rework were built to produce, so this is urgent in the same way). Phase C is dead-code/dependency removal — zero behavior change, safe to do anytime, done before D so D's refactors touch a cleaner file. Phase D is refactor/polish — no user-facing behavior change, lowest urgency. Phase E is the Premium-lock UI, placed last because it depends on Phase A's backend tier-gate already existing.

---

## Phase A — Security & authorization fixes

**Why:** Three of these are live gaps an ordinary user could hit today (not theoretical attacker scenarios): a Basic tenant's saved "Performance" setting silently does nothing (the bug that started this audit), any logged-in role can modify tenant-wide settings regardless of permission, and unauthenticated rate-limiting can be bypassed by spoofing a header. A fourth (hardcoded phone number) is a plain data-hygiene fix.

**Files:**
- Modify: `main.py` (`update_tenant_settings`, `get_rate_limit_key`, `create_chat_completion`'s `ChatCompletionRequest`, `dispatch_system_alert`'s constants)
- Test: `tests/test_tenant_settings_authorization.py`, `tests/test_rate_limit_key.py`, `tests/test_chat_completion_validation.py` (new)

**Scope:**

1. **Reject `routing_mode: "PERFORMANCE"` for non-Premium tenants in `PATCH /v1/tenant/settings`** (`main.py:796`), mirroring the existing `402 Payment Required` pattern already used at request time (`main.py:517-520`). ECO and SMART remain valid for every tier.
2. **Add a role check to `update_tenant_settings`**: only `TENANT_ADMIN` (not `DEVELOPER`) may call it — same pattern as the `TENANT_ADMIN`-only check already built for `rotate_api_key` (`main.py:872`). Requires reading the JWT's `role` claim, not just resolving a `Tenant` row.
3. **Stop trusting `X-Forwarded-For` by default.** `get_rate_limit_key` (`main.py:44-53`) only uses the forwarded header if a new `TRUST_PROXY_HEADERS=true` env var is set; otherwise falls back to `request.client.host`. This is safe to ship without knowing the exact hosting proxy setup — it defaults to the safer behavior and lets you opt in once you confirm your host (Vercel/HF Space) sets this header itself.
4. **Add request validation to `ChatCompletionRequest`**: `messages: List[Message] = Field(min_length=1)` so an empty list is rejected by Pydantic (422) instead of crashing with an unhandled `IndexError` (500) at `main.py:492`. Also cap prompt size — add a `MAX_PROMPT_CHARS = 20000` constant and reject longer prompts with a 413, closing the unbounded-cost-abuse vector.
5. **Move the hardcoded phone number to an environment variable.** `DEVELOPER_WHATSAPP_TO` (`main.py:172`) reads from `os.environ.get("DEVELOPER_WHATSAPP_TO")` instead of a literal string; add it to `.env` (not committed) and document it as required for the WhatsApp alert feature to function.

**Acceptance:**
- A Basic-tier tenant's `PATCH` with `routing_mode: "PERFORMANCE"` returns 402, unchanged tenant row.
- A `DEVELOPER`-role JWT calling `PATCH /v1/tenant/settings` returns 403.
- With `TRUST_PROXY_HEADERS` unset, a spoofed `X-Forwarded-For` header has no effect on the rate-limit key.
- An empty `messages` array returns 422, not a 500.
- A prompt over 20,000 characters returns 413.
- `grep -rn "918807387379" main.py` returns no matches.

---

## Phase B — Data-integrity bug fixes

**Why:** The streaming billing gap is the most consequential single finding in the whole audit — if most real traffic streams, the reliability and upsell numbers built across Phase 0 and Phase 3 of the dashboard rework are wrong for the majority of your data, silently. The duplicated pricing logic (finding #10) is fixed in the same phase because the correct fix for #7 is to extract a shared cost-calculation function that both the streaming and non-streaming paths call — fixing the bug and the duplication in one motion, not two.

**Files:**
- Modify: `main.py` (extract `compute_provider_cost()`, fix `generate_live_stream`, fix `create_chat_completion`'s non-streaming branch to use the shared helper)
- Modify: `sanitizer.py` (add `IN_PAN`, `IN_AADHAAR` to the entities list)
- Test: `tests/test_provider_cost.py`, `tests/test_streaming_billing.py` (new)

**Scope:**

1. **Extract a shared `compute_provider_cost(actual_provider: str, actual_model: str, p_tokens: int, c_tokens: int) -> float`** function (module level in `main.py`), containing the exact pricing logic currently duplicated at `main.py:565-570` (non-streaming) and `main.py:148-151` (streaming). Both call sites call this one function instead.
2. **Fix `generate_live_stream` to preserve fallback awareness.** Currently it overwrites the fallback-aware `actual_provider` returned by `inference_manager.get_response()` based on chunk shape (`main.py:125,133`). Instead, capture `planned_provider` (the provider passed in as `target_provider`) before the call, and compute `request_used_fallback = actual_provider != planned_provider` immediately after `get_response()` returns — the same pattern already used correctly in the non-streaming branch (`main.py:580`).
3. **Thread `request_was_tier_capped` into the streaming path.** `create_chat_completion` already computes this flag before branching on `payload.stream` (`main.py:511`) — pass it as a new parameter to `generate_live_stream(..., was_tier_capped=request_was_tier_capped)`, and use it in that function's `log_request` call.
4. **Add `IN_PAN` and `IN_AADHAAR` to `sanitizer.py`'s entity list** (`sanitizer.py:30`) — confirmed these recognizers already load at startup (`InPanRecognizer`, `InAadhaarRecognizer` in your own boot logs), they're just never actually requested in the `analyze()` call.

**Acceptance:**
- A streaming request that triggers provider fallback (mock the primary provider to fail) results in a `UsageLog` row with `used_fallback=True` — verified via a test that mocks `inference_manager.get_response` to return a different provider than requested, same mocking pattern as the existing non-streaming fallback test.
- A streaming request from a Basic tenant that would have used a premium model gets a `UsageLog` row with `was_tier_capped=True`.
- `sanitize_prompt("My PAN is ABCDE1234F")` and `sanitize_prompt("My Aadhaar is 234123412346")` both redact those values.
- Both streaming and non-streaming paths produce identical cost for the same `(provider, model, p_tokens, c_tokens)` input — verified with a direct unit test on `compute_provider_cost`, not just an integration test.

---

## Phase C — Dead code & dependency cleanup

**Why:** Zero behavior change, safe to do independently of everything else. Removing unused heavy dependencies (`arize-phoenix` alone is a large package) shrinks install time and attack surface for no cost.

**Files:**
- Modify: `requirements-dev.txt` (remove `arize-phoenix`, `opentelemetry-instrumentation-fastapi`, `openinference-instrumentation`)
- Modify: `requirements.txt` (pin `slowapi==0.1.9`, `pyjwt==2.13.0`, `twilio==9.10.9`, `google-genai==2.8.0` — versions confirmed already installed via `pip freeze`)
- Modify: `main.py` (remove unused `HTMLResponse` import, line 10)

**Scope:** Purely subtractive/pinning — no new tests needed since nothing behavioral changes. Verification is: full test suite still passes, and `python -c "import main"` still succeeds after the import removal.

**Acceptance:**
- `pytest tests/` — all tests pass, same count as before this phase.
- `grep -n "HTMLResponse" main.py` returns no matches.
- `pip install -r requirements.txt` succeeds with the pinned versions.

---

## Phase D — Refactor / polish

**Why:** No user-facing behavior change, purely maintainability. Lowest priority — do this once A–C are stable, and skip it first if time runs short.

**Files:**
- Modify: `main.py` (extract `get_jwt_claims()`, reuse across 4 call sites; move Twilio client construction to module level; narrow the broad `except Exception` in `provider.py` if feasible)
- Modify: `sanitizer.py` (lazy-load the Presidio analyzer, matching `router.py`'s lazy-load pattern)

**Scope:**

1. **Extract `get_jwt_claims(request: Request) -> dict`** — the shared "read Bearer header, decode JWT, raise a consistent 403 on failure" logic currently duplicated in `get_tenant_from_session_or_key`, `get_current_admin_user`, `rotate_api_key`, and `change_password` (`main.py`, four separate near-identical blocks). Each of the four call sites then does its own additional check (tenant lookup, role check, etc.) on top of the shared claims dict. Standardize on 403 for "missing/invalid auth" everywhere (currently `change_password` uses 401 inconsistently) — confirm this doesn't break any existing test expecting 401 before changing it.
2. **Move Twilio `Client(...)` construction out of `dispatch_system_alert`** into a module-level singleton, constructed once.
3. **Lazy-load `sanitizer.py`'s `AnalyzerEngine`** — wrap the current module-level initialization in an `initialize_sanitizer()` function called from `main.py`'s `lifespan()` alongside `router.initialize_router()`, matching the existing lazy-load pattern instead of loading at import time.

**Acceptance:**
- Full test suite passes with identical behavior (this phase should produce zero test changes if done correctly, since it doesn't change observable behavior — a good sign if a test needs to change here, stop and check whether behavior actually shifted unintentionally).
- App cold-start log order shows the sanitizer initializing during the boot sequence (alongside "Compiling Route Layer"), not before "Booting Core Systems" prints.

---

## Phase E — Premium-lock UI

**Why:** Depends on Phase A's backend tier-gate (item 1) already existing — the UI lock is the second half of that fix, not a substitute for it. Placed last since it's a small, self-contained frontend change with no ambiguity once Phase A lands.

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx` (Routing tab, `activeTab === "Routing"` block)

**Scope:**
- When `metrics?.plan_tier !== "PREMIUM"`, the "PERFORMANCE" radio option in the Routing tab renders disabled, greyed out, with a small lock icon and "Requires Premium" label instead of its normal description text.
- Clicking the disabled option does nothing (no `onChange` fires); a short inline note appears instead: "Upgrade to Premium to unlock Performance mode."
- ECO and SMART remain fully interactive and unchanged for every tier.
- If a Basic tenant somehow already has `routing_mode: "PERFORMANCE"` saved from before Phase A shipped (shouldn't happen going forward, but could exist from before this fix), the radio group still visually shows it as selected-but-locked rather than silently reverting it — avoids confusing "why did my setting change" surprise; the next real save will be rejected by the Phase A backend gate and prompt the user to pick ECO or SMART instead.

**Acceptance:**
- Manual/browser check (or `preview_start` walkthrough if you want one this time): logging in as the seeded Basic tenant shows the Performance option locked; logging in as the seeded Premium tenant shows it fully interactive.

---

## Explicitly out of scope for this pass

- **JWT-in-`localStorage` → httpOnly cookies.** This is a real hardening idea (finding #6) but it's a genuine architecture change — it needs CSRF protection, `SameSite`/cookie-domain configuration, and touches CORS credentials handling across every endpoint. Bundling it into this cleanup pass risks destabilizing auth for a marginal security gain given the current threat model. Recommend treating this as its own dedicated project if you want to pursue it, not a line item here.
- **Full conversation-history support for multi-turn chat** (finding #8, Gemini dropping all but the last message). This is a real capability gap, but fixing it properly means threading full message history through routing, both provider call paths, and reshaping Gemini's `contents` payload format — a feature-sized change, not a bug-sized one. Flagging it as a separate future item rather than folding it into this hardening pass.
- **Narrowing `except Exception` in `InferenceManager.get_response`** beyond what's listed in Phase D — full exception-type auditing of the Groq/Gemini SDKs is a larger investigation; Phase D only does this if it's cheap once we're in the file, otherwise it's deferred.

---

## Next step

Recommended order is A → B → C → D → E, since A and B are the only phases with live user-facing consequences today. C and D are safe to interleave or skip under time pressure. Pick which phase to expand into a full execution-ready TDD plan first.
