from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, UsageLog, log_request, Tenant, hash_api_key, provision_new_tenant, User, hash_password, verify_password, PLAN_PRICING
import os
import time
import json
import secrets
from fastapi import FastAPI, HTTPException, Security, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from sqlalchemy import func

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import jwt
from datetime import datetime, timedelta, timezone
from twilio.rest import Client
import httpx

# ---------------------------------------------------------
# CORE STATE ENGINE & SECURITY INITIALIZATIONS
# ---------------------------------------------------------
def get_tenant_rate_limit(key: str = None) -> str:
    if not key:
        return "60/minute"
    db = SessionLocal()
    try:
        # 'key' is already the hashed API key returned by get_rate_limit_key
        tenant = db.query(Tenant).filter(Tenant.api_key == key, Tenant.is_active == True).first()
        if tenant and tenant.plan_tier == "PREMIUM":
            return "1000/minute"
    except Exception:
        pass
    finally:
        db.close()
    return "60/minute"

def get_rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return hash_api_key(api_key)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"

limiter = Limiter(key_func=get_rate_limit_key)

from provider import inference_manager
import router
from sanitizer import sanitize_prompt

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🌐 [GATEWAY] Booting Core Systems...")
    router.initialize_router()
    yield
    print("🛑 [GATEWAY] Offline.")

app = FastAPI(title="Hybrid Semantic Router API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://hybrid-router.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------
# DATA MODEL SCHEMAS (Pydantic Validation Layer)
# ---------------------------------------------------------
class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

class LoginRequest(BaseModel):
    username: str
    password: str

class TenantSettingsUpdate(BaseModel):
    routing_mode: Optional[str] = None
    fallback_provider: Optional[str] = None
    monthly_budget_cap: Optional[float] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ---------------------------------------------------------
# OBSERVABILITY STREAMING GENERATOR ENGINE
# ---------------------------------------------------------
async def generate_live_stream(user_prompt: str, target_model: str, target_provider: str, fallback_provider: str, tenant_id: str):
    try:
        response, actual_provider, actual_model = await inference_manager.get_response(
            model_name=target_model,
            messages=[{"role": "user", "content": user_prompt}],
            provider=target_provider,
            fallback_provider=fallback_provider,
            stream=True
        )
        
        p_tokens = 0
        c_tokens = 0
        
        async for chunk in response:
            content = ""
            if hasattr(chunk, "choices"):
                actual_provider = "groq"
                if getattr(chunk, "usage", None):
                    p_tokens = chunk.usage.prompt_tokens
                    c_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content or ""
            else:
                actual_provider = "gemini"
                actual_model = "gemini-2.5-flash" if "llama" in target_model else target_model
                if getattr(chunk, "usage_metadata", None):
                    p_tokens = chunk.usage_metadata.prompt_token_count
                    c_tokens = chunk.usage_metadata.candidates_token_count
                content = chunk.text or ""
                
            payload = {
                "id": "chatcmpl-hybrid",
                "object": "chat.completion.chunk",
                "model": actual_model,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(payload)}\n\n"
        
        if actual_provider == "groq":
            cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in actual_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        else:
            cost = (p_tokens * 0.075 + c_tokens * 0.30) / 1_000_000
            
        import asyncio
        await asyncio.to_thread(log_request, tenant_id, actual_model, p_tokens, c_tokens, cost)
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

# ---------------------------------------------------------
# CONSTANTS & CONFIGURATIONS
# ---------------------------------------------------------
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("FATAL: JWT_SECRET environment variable is unset. Cannot start application in a secure state.")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "ACYourTwilioAccountSidHere")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "YourTwilioAuthTokenHere")
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"  # Twilio standard verified sandbox number
DEVELOPER_WHATSAPP_TO = "whatsapp:+918807387379"  # Replace with your phone number!

# ---------------------------------------------------------
# OBSERVABILITY UTILITIES (WhatsApp Alerts Engine)
# ---------------------------------------------------------
async def dispatch_system_alert(severity: str, component: str, message: str):
    """
    Asynchronously fires real-time system alerts directly to your personal WhatsApp 
    whenever a primary vendor node fails or a critical cluster incident occurs.
    """
    print(f"🚨 [OBSERVABILITY WARNING] [{severity.upper()}] Component: {component} -> {message}")
    
    whatsapp_body = (
        f"💥 *[HYBRID ROUTER ALARM]* 💥\n\n"
        f"• *SEVERITY:* `{severity.upper()}`\n"
        f"• *COMPONENT:* `{component}`\n"
        f"• *TIMESTAMP:* `{datetime.now(timezone.utc).isoformat()} UTC`\n\n"
        f"⚠️ *DIAGNOSTIC DETAILS:*\n{message}"
    )
    
    try:
        # Initialize Twilio Client Engine locally
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message_sent = client.messages.create(
            body=whatsapp_body,
            from_=TWILIO_WHATSAPP_FROM,
            to=DEVELOPER_WHATSAPP_TO
        )
        print(f"✉️ [WHATSAPP DISPATCHED] Alert delivered to mobile gateway. SID: {message_sent.sid}")
    except Exception as e:
        print(f"⚠️ [OBSERVABILITY EXCEPTION] Failed to transmit WhatsApp telemetry: {str(e)}")

# ---------------------------------------------------------
# API ACCREDITATION GUARD (Security Dependency Injections)
# ---------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_authenticated_tenant(key: str = Security(api_key_header)):
    db = SessionLocal()
    try:
        hashed_key = hash_api_key(key)
        tenant = db.query(Tenant).filter(Tenant.api_key == hashed_key, Tenant.is_active == True).first()
        if not tenant:
            raise HTTPException(status_code=403, detail="Invalid or deactivated credentials.")
        db.expunge(tenant)
        return tenant
    finally:
        db.close()

async def get_tenant_from_session_or_key(request: Request):
    db = SessionLocal()
    try:
        # 1. Check X-API-Key header first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            hashed_key = hash_api_key(api_key)
            tenant = db.query(Tenant).filter(Tenant.api_key == hashed_key, Tenant.is_active == True).first()
            if tenant:
                db.expunge(tenant)
                return tenant
        
        # 2. Check Authorization header (Bearer token)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                tenant_id = payload.get("tenant_id")
                if tenant_id:
                    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
                    if tenant:
                        db.expunge(tenant)
                        return tenant
            except jwt.PyJWTError:
                pass
                
        raise HTTPException(status_code=403, detail="Invalid or deactivated credentials.")
    finally:
        db.close()

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

async def send_provisioning_email(customer_email: str, tenant_id: str, api_key: str, temp_password: str = None):
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        print("⚠️ [EMAIL CLIENT] RESEND_API_KEY is not set. Cannot send token delivery email.")
        return False
    
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {resend_api_key}",
        "Content-Type": "application/json"
    }
    
    credentials_section = ""
    if temp_password:
        credentials_section = f"""
        <h4>Dashboard Login</h4>
        <p>Log in to view your billing, manage your routing settings, and get your API key:</p>
        <p>Dashboard URL: <a href="https://hybrid-router.vercel.app/login">https://hybrid-router.vercel.app/login</a></p>
        <ul>
            <li><strong>Username:</strong> {customer_email}</li>
            <li><strong>Password:</strong> <code>{temp_password}</code></li>
        </ul>
        <p style="font-size: 0.85em; color: #666;">Note: We recommend changing your password after your initial login.</p>
        """

    payload = {
        "from": "onboarding@resend.dev",
        "to": customer_email,
        "subject": "Your Hybrid Router API Key & Onboarding Details",
        "html": f"""
        <h3>Welcome to Hybrid Router!</h3>
        <p>Your tenant profile <strong>{tenant_id}</strong> has been successfully provisioned.</p>
        <p>Here is your secure cleartext API Key:</p>
        <pre style="background-color: #f4f4f4; padding: 10px; border-radius: 5px; font-weight: bold; font-family: monospace;">{api_key}</pre>
        <p><strong>IMPORTANT:</strong> Guard this key carefully. It will not be shown again.</p>
        {credentials_section}
        """
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in [200, 201]:
                print(f"✉️ [EMAIL CLIENT] Secure token delivered successfully to {customer_email}")
                return True
            else:
                print(f"❌ [EMAIL CLIENT] Failed to send email. Resend response: {response.text}")
                return False
    except Exception as e:
        print(f"⚠️ [EMAIL CLIENT] Exception during email transmission: {str(e)}")
        return False

# ---------------------------------------------------------
# PHASE 5: DOWNTIME-FREE IDENTITY GATEWAY ENDPOINTS
# ---------------------------------------------------------
@app.post("/v1/auth/login")
@limiter.limit("10/minute")
async def login_dashboard_session(request: Request, payload: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == payload.username).first()
        
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        
        token_expiry = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_claims = {
            "sub": user.username,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "exp": token_expiry
        }
        
        access_token = jwt.encode(token_claims, JWT_SECRET, algorithm=JWT_ALGORITHM)
        print(f"🔒 [AUTH] Issued short-lived JWT session token for operator: {user.username} ({user.role})")
        
        return {
            "status": "success",
            "access_token": access_token,
            "token_type": "bearer",
            "user_info": {
                "username": user.username,
                "role": user.role,
                "tenant_id": user.tenant_id
            }
        }
    finally:
        db.close()

# ---------------------------------------------------------
# SECURITY WEBHOOK SIGNATURE VERIFICATION ENGINE
# ---------------------------------------------------------
def verify_razorpay_signature(body: bytes, signature: str, secret: str) -> bool:
    """Cryptographically verifies that the inbound webhook payload matches Razorpay's webhook secret."""
    import hmac
    import hashlib
    if not signature or not secret:
        return False
    try:
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False

# ---------------------------------------------------------
# PHASE 6: UN-AUTHENTICATED WEBHOOK INGESTION ENGINES
# ---------------------------------------------------------
@app.post("/v1/webhooks/razorpay")
async def handle_razorpay_webhook(request: Request, background_tasks: BackgroundTasks):
    razorpay_signature = request.headers.get("X-Razorpay-Signature")
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")

    if not webhook_secret:
        print("🚨 [WEBHOOK CRITICAL] RAZORPAY_WEBHOOK_SECRET is not set. Dropping event.")
        raise HTTPException(status_code=500, detail="Webhook verification is not configured.")

    body = await request.body()
    if not verify_razorpay_signature(body, razorpay_signature, webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature.")

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event = data.get("event", "")
    payment_entity = data.get("payload", {}).get("payment", {}).get("entity", {})

    # ------------------------------------------------------------------
    # EVENT: payment.captured — provision new tenant on successful payment
    # ------------------------------------------------------------------
    if event == "payment.captured":
        customer_identifier = f"org_{payment_entity.get('id', '')}"
        inferred_tier = "PREMIUM" if payment_entity.get("amount", 0) >= 400000 else "BASIC"

        db = SessionLocal()
        try:
            if db.query(Tenant).filter(Tenant.id == customer_identifier).first():
                return {"status": "skipped", "reason": f"{customer_identifier} already provisioned."}

            generated_live_key = provision_new_tenant(db_session=db, tenant_id=customer_identifier, plan_tier=inferred_tier)

            import secrets as _secrets
            customer_email = payment_entity.get("email") or "customer@example.com"
            temp_password = _secrets.token_urlsafe(8)
            new_user = User(
                username=customer_email,
                password_hash=hash_password(temp_password),
                role="TENANT_ADMIN",
                tenant_id=customer_identifier
            )
            db.add(new_user)
            db.commit()

            background_tasks.add_task(send_provisioning_email, customer_email, customer_identifier, generated_live_key, temp_password)
            return {"status": "success", "provisioned_id": customer_identifier, "assigned_tier": inferred_tier}

        except Exception as e:
            db.rollback()
            print(f"🚨 [WEBHOOK ERROR] Onboarding failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Account onboarding failed.")
        finally:
            db.close()

    # ------------------------------------------------------------------
    # EVENT: payment.failed — deactivate tenant on failed renewal payment
    # ------------------------------------------------------------------
    elif event == "payment.failed":
        customer_email = payment_entity.get("email")
        if customer_email:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.username == customer_email).first()
                if user and user.tenant_id:
                    tenant_row = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
                    if tenant_row and tenant_row.is_active:
                        tenant_row.is_active = False
                        db.commit()
                        print(f"🚨 [WEBHOOK] Tenant {user.tenant_id} deactivated — payment failed.")
                        background_tasks.add_task(
                            send_provisioning_email, customer_email, user.tenant_id,
                            "PAYMENT_FAILED", None
                        )
            finally:
                db.close()
        return {"status": "processed", "event": event}

    # ------------------------------------------------------------------
    # EVENT: subscription.cancelled — deactivate tenant on cancellation
    # ------------------------------------------------------------------
    elif event == "subscription.cancelled":
        sub_entity = data.get("payload", {}).get("subscription", {}).get("entity", {})
        customer_email = sub_entity.get("notes", {}).get("email") or payment_entity.get("email")
        if customer_email:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.username == customer_email).first()
                if user and user.tenant_id:
                    tenant_row = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
                    if tenant_row:
                        tenant_row.is_active = False
                        db.commit()
                        print(f"🔕 [WEBHOOK] Tenant {user.tenant_id} deactivated — subscription cancelled.")
            finally:
                db.close()
        return {"status": "processed", "event": event}

    return {"status": "ignored", "event": event}

# ---------------------------------------------------------
# CORE PLATFORM RUNTIME COMPLETIONS ROUTE
# ---------------------------------------------------------
@app.post("/v1/chat/completions")
@limiter.limit(get_tenant_rate_limit) 
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest, 
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_authenticated_tenant)
):
    if router.sr is None:
        raise HTTPException(status_code=503, detail="AI Core booting...")

    user_prompt = sanitize_prompt(payload.messages[-1].content)
    start_time = time.time()
    
    tenant_mode = tenant.routing_mode.upper() if tenant.routing_mode else "SMART"
    
    if tenant_mode == "PERFORMANCE":
        matched_route = "complex_reasoning"
        print(f"🔵 [LLM OPTION] Performance Mode Active. Short-circuiting directly to Premium Track.")
    else:
        route_choice = router.sr(user_prompt)
        matched_route = route_choice.name if route_choice.name else "complex_reasoning"
        
        if tenant_mode == "ECO" and matched_route == "complex_reasoning":
            matched_route = "simple_chat"
            print(f"🟢 [LLM OPTION] Eco Mode Active. Demoting unclassified route to Simple Chat for max savings.")

    routing_latency = (time.time() - start_time) * 1000
    print(f"[ROUTER] Decision: {matched_route.upper()} (Overhead: {routing_latency:.2f}ms | Tenant Mode: {tenant_mode})")
    
    mapping = router.MODEL_MAPPINGS.get(matched_route, {"model": "llama-3.3-70b-versatile", "provider": "groq"})

    # Graceful degradation rules for adaptive tier matching bounds
    request_was_tier_capped = False
    if mapping["provider"] == "gemini" or "70b" in mapping["model"]:
        if tenant.plan_tier != "PREMIUM":
            if payload.model not in ["hybrid-gateway", "default", "", None]:
                raise HTTPException(
                    status_code=402,
                    detail="Payment Required: Upgrade to Premium to unlock advanced inference tiers."
                )
            else:
                matched_route = "simple_chat"
                mapping = router.MODEL_MAPPINGS.get(matched_route)
                request_was_tier_capped = True
                print(f"🔶 [TIER ENFORCEMENT] Demoting route to Simple Chat for BASIC tier: {tenant.id}")

    if matched_route == "safety_block":
        return StreamingResponse(iter(["data: [BLOCKED]\n\n"]), media_type="text/event-stream")

    if payload.stream:
        return StreamingResponse(
            generate_live_stream(
                user_prompt=user_prompt, 
                target_model=mapping["model"], 
                target_provider=mapping["provider"], 
                fallback_provider=tenant.fallback_provider,
                tenant_id=tenant.id
            ), 
            media_type="text/event-stream"
        )
    else:
        planned_provider = mapping["provider"]
        planned_model = mapping["model"]
        
        provider_start_time = time.time()
        
        response, actual_provider, actual_model = await inference_manager.get_response(
            model_name=planned_model,
            messages=[{"role": "user", "content": user_prompt}],
            provider=planned_provider,
            fallback_provider=tenant.fallback_provider,
            stream=False
        )
        
        if actual_provider != planned_provider:
            print(f"⚠️ [GATEWAY INCIDENT] Primary Provider '{planned_provider}' failed. Triggering automatic cluster failover.")
            alert_details = (
                f"Primary provider `{planned_provider}` failed or timed out. "
                f"Gateway has failed over to backup provider `{actual_provider}` for tenant `{tenant.id}` "
                f"to preserve client session connectivity workflows without data loss metrics."
            )
            await dispatch_system_alert(severity="CRITICAL", component="VENDOR_FAILOVER_MATRIX", message=alert_details)
        
        provider_latency_ms = (time.time() - provider_start_time) * 1000
        
        if hasattr(response, "choices"):
            content = response.choices[0].message.content
            p_tokens = response.usage.prompt_tokens if getattr(response, "usage", None) else 0
            c_tokens = response.usage.completion_tokens if getattr(response, "usage", None) else 0
            cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in actual_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        else:
            content = response.text
            p_tokens = response.usage_metadata.prompt_token_count if getattr(response, "usage_metadata", None) else 0
            c_tokens = response.usage_metadata.candidates_token_count if getattr(response, "usage_metadata", None) else 0
            cost = (p_tokens * 0.075 + c_tokens * 0.30) / 1_000_000
            
        print(f"📊 [TELEMETRY STATE] Processing Complete. Overhead: {provider_latency_ms:.2f}ms | Target: {actual_provider.upper()}")

        request_used_fallback = actual_provider != planned_provider
        background_tasks.add_task(log_request, tenant.id, actual_model, p_tokens, c_tokens, cost, request_used_fallback, request_was_tier_capped)
        return {
            "status": "success", 
            "data": str(content), 
            "routing_debug": {
                "latency_ms": provider_latency_ms, 
                "provider": actual_provider
            }
        }

# ---------------------------------------------------------
# HISTORICAL METRICS ANALYTICS ENDPOINT
# ---------------------------------------------------------
@app.get("/v1/analytics")
async def get_analytics(tenant: Tenant = Depends(get_tenant_from_session_or_key)):
    db = SessionLocal()
    try:
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        stats = db.query(
            func.sum(UsageLog.billed_usage_cost).label("total_billed"),
            func.sum(UsageLog.reference_cost).label("total_reference"),
            func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens"),
        ).filter(UsageLog.tenant_id == tenant.id, UsageLog.timestamp >= month_start).first()

        total_requests = db.query(UsageLog).filter(
            UsageLog.tenant_id == tenant.id, UsageLog.timestamp >= month_start
        ).count()
        fallback_count = db.query(UsageLog).filter(
            UsageLog.tenant_id == tenant.id, UsageLog.used_fallback == True, UsageLog.timestamp >= month_start
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
            "monthly_budget_cap": tenant.monthly_budget_cap,
            "recent_logs": recent_logs,
            "api_key_hash": tenant.api_key,
        }
    finally:
        db.close()

# ---------------------------------------------------------
# DAILY TIMESERIES ENDPOINT (trend chart / forecast source data)
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# SUPER_ADMIN — PLATFORM-WIDE REVENUE, COST, PROFIT ROLLUP
# ---------------------------------------------------------
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

        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        usage_stats = db.query(
            func.sum(UsageLog.billed_usage_cost).label("total_billed"),
            func.sum(UsageLog.cost_incurred).label("total_cogs"),
            func.sum(UsageLog.reference_cost).label("total_reference"),
        ).filter(UsageLog.timestamp >= month_start).first()

        total_billed = float(usage_stats.total_billed or 0)
        total_cogs = float(usage_stats.total_cogs or 0)
        total_reference = float(usage_stats.total_reference or 0)

        total_revenue = total_base_fee_revenue + total_billed
        platform_profit = total_revenue - total_cogs

        fallback_trigger_count = db.query(UsageLog).filter(
            UsageLog.used_fallback == True, UsageLog.timestamp >= month_start
        ).count()

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

# ---------------------------------------------------------
# SUPER_ADMIN — PER-TENANT PROFIT BREAKDOWN
# ---------------------------------------------------------
@app.get("/v1/admin/tenants")
async def get_admin_tenants(admin: dict = Depends(get_current_admin_user)):
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).all()
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = []
        for t in tenants:
            usage_stats = db.query(
                func.sum(UsageLog.billed_usage_cost).label("billed"),
                func.sum(UsageLog.cost_incurred).label("cogs"),
            ).filter(UsageLog.tenant_id == t.id, UsageLog.timestamp >= month_start).first()

            last_active_row = db.query(
                func.max(UsageLog.timestamp).label("last_active"),
            ).filter(UsageLog.tenant_id == t.id).first()

            # Lifetime count, not month-scoped — a sustained pattern of tier-capping is the upsell signal,
            # not a count that resets to zero every month regardless of how consistently a client hits it.
            tier_capped_count = db.query(UsageLog).filter(
                UsageLog.tenant_id == t.id, UsageLog.was_tier_capped == True
            ).count()

            billed = float(usage_stats.billed or 0)
            cogs = float(usage_stats.cogs or 0)
            base_fee = PLAN_PRICING.get(t.plan_tier, {}).get("base_fee", 0.0)
            revenue = base_fee + billed

            last_active = last_active_row.last_active
            churn_risk_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
            churn_risk = last_active is None or last_active < churn_risk_cutoff

            rows.append({
                "tenant_id": t.id,
                "plan_tier": t.plan_tier,
                "is_active": t.is_active,
                "revenue_this_period": round(revenue, 4),
                "cogs_this_period": round(cogs, 4),
                "profit_this_period": round(revenue - cogs, 4),
                "last_active": last_active.isoformat() if last_active else None,
                "monthly_budget_cap": t.monthly_budget_cap,
                "churn_risk": churn_risk,
                "tier_capped_count": tier_capped_count,
            })

        rows.sort(key=lambda r: r["profit_this_period"])
        return {"tenants": rows}
    finally:
        db.close()

# ---------------------------------------------------------
# SUPER_ADMIN — PLATFORM-WIDE DAILY TIMESERIES (INFRASTRUCTURE TREND)
# ---------------------------------------------------------
@app.get("/v1/admin/timeseries")
async def get_admin_timeseries(days: int = 30, admin: dict = Depends(get_current_admin_user)):
    db = SessionLocal()
    try:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days - 1)

        logs = db.query(UsageLog).filter(UsageLog.timestamp >= start_date).all()

        buckets = {
            (start_date + timedelta(days=i)).isoformat(): {
                "date": (start_date + timedelta(days=i)).isoformat(),
                "request_count": 0,
                "fallback_count": 0,
            }
            for i in range(days)
        }

        for log in logs:
            key = log.timestamp.date().isoformat()
            if key in buckets:
                buckets[key]["request_count"] += 1
                if log.used_fallback:
                    buckets[key]["fallback_count"] += 1

        daily = [buckets[k] for k in sorted(buckets.keys())]
        return {"daily": daily}
    finally:
        db.close()

# ---------------------------------------------------------
# TENANT SETTINGS ENDPOINT
# ---------------------------------------------------------
VALID_ROUTING_MODES = {"ECO", "SMART", "PERFORMANCE"}
VALID_PROVIDERS = {"groq", "gemini"}

@app.patch("/v1/tenant/settings")
async def update_tenant_settings(
    update: TenantSettingsUpdate,
    tenant: Tenant = Depends(get_tenant_from_session_or_key)
):
    if update.routing_mode and update.routing_mode.upper() not in VALID_ROUTING_MODES:
        raise HTTPException(status_code=422, detail=f"routing_mode must be one of {sorted(VALID_ROUTING_MODES)}")
    if update.fallback_provider and update.fallback_provider.lower() not in VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"fallback_provider must be one of {sorted(VALID_PROVIDERS)}")

    db = SessionLocal()
    try:
        tenant_row = db.query(Tenant).filter(Tenant.id == tenant.id).first()
        if update.routing_mode:
            tenant_row.routing_mode = update.routing_mode.upper()
        if update.fallback_provider:
            tenant_row.fallback_provider = update.fallback_provider.lower()
        if update.monthly_budget_cap is not None:
            tenant_row.monthly_budget_cap = update.monthly_budget_cap
        db.commit()
        return {
            "status": "success",
            "routing_mode": tenant_row.routing_mode,
            "fallback_provider": tenant_row.fallback_provider,
            "monthly_budget_cap": tenant_row.monthly_budget_cap,
        }
    finally:
        db.close()

# ---------------------------------------------------------
# API KEY ROTATION ENDPOINT
# ---------------------------------------------------------
@app.post("/v1/tenant/api-key/rotate")
async def rotate_api_key(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing or invalid authorization header.")
    try:
        claims = jwt.decode(auth_header.split(" ")[1], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired session token.")

    if claims.get("role") != "TENANT_ADMIN":
        raise HTTPException(status_code=403, detail="Only a tenant admin can rotate the API key.")

    tenant_id = claims.get("tenant_id")
    db = SessionLocal()
    try:
        tenant_row = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant_row:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        raw_key = f"sk_live_{secrets.token_hex(16)}"
        tenant_row.api_key = hash_api_key(raw_key)
        db.commit()
        return {"status": "success", "api_key": raw_key}
    finally:
        db.close()

# ---------------------------------------------------------
# PASSWORD CHANGE ENDPOINT
# ---------------------------------------------------------
@app.post("/v1/auth/change-password")
async def change_password(payload: ChangePasswordRequest, request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")

    try:
        claims = jwt.decode(auth_header.split(" ")[1], JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = claims.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session token.")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        user.password_hash = hash_password(payload.new_password)
        db.commit()
        return {"status": "success", "message": "Password updated successfully."}
    finally:
        db.close()

# ---------------------------------------------------------
# PLATFORM SYSTEM STATUS ENDPOINT
# ---------------------------------------------------------
@app.get("/")
async def get_system_status():
    return {
        "status": "online",
        "service": "Hybrid Semantic Router API Gateway",
        "version": "1.0.0"
    }