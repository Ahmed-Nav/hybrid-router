from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, UsageLog, log_request, Tenant, hash_api_key, provision_new_tenant, User, hash_password, verify_password
import os
import time
import json
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
def get_tenant_rate_limit(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return "60/minute"
    db = SessionLocal()
    try:
        hashed_key = hash_api_key(api_key)
        tenant = db.query(Tenant).filter(Tenant.api_key == hashed_key, Tenant.is_active == True).first()
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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

class StripeCustomerDetails(BaseModel):
    email: Optional[str] = None

class StripeObject(BaseModel):
    customer: str
    amount_total: int
    currency: str
    customer_details: Optional[StripeCustomerDetails] = None
    custom_fields: Optional[List[dict]] = None

class StripeData(BaseModel):
    object: StripeObject

class StripeWebhookPayload(BaseModel):
    id: str
    type: str
    data: StripeData

class RazorpayPaymentEntity(BaseModel):
    id: str
    amount: int
    currency: str
    email: Optional[str] = None
    contact: Optional[str] = None

class RazorpayPayment(BaseModel):
    entity: RazorpayPaymentEntity

class RazorpayPayload(BaseModel):
    payment: RazorpayPayment

class RazorpayWebhookPayload(BaseModel):
    event: str
    payload: RazorpayPayload


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
            
        log_request(tenant_id, actual_model, p_tokens, c_tokens, cost)
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

async def send_provisioning_email(customer_email: str, tenant_id: str, api_key: str):
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        print("⚠️ [EMAIL CLIENT] RESEND_API_KEY is not set. Cannot send token delivery email.")
        return False
    
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {resend_api_key}",
        "Content-Type": "application/json"
    }
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
async def login_dashboard_session(payload: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == payload.username).first()
        
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid operator identity or password alignment.")
        
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
def verify_stripe_signature(payload_body: bytes, sig_header: str, secret: str) -> bool:
    """Cryptographically verifies that the inbound webhook payload matches Stripe's signing key."""
    import hmac
    import hashlib
    if not sig_header or not secret:
        return False
    try:
        parts = dict(item.split('=') for item in sig_header.split(','))
        timestamp = parts.get('t')
        signature = parts.get('v1')
        
        if not timestamp or not signature:
            return False
            
        signed_payload = f"{timestamp}.{payload_body.decode('utf-8')}".encode('utf-8')
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False

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
@app.post("/v1/webhooks/stripe")
async def handle_stripe_billing_webhook(payload: StripeWebhookPayload, request: Request, background_tasks: BackgroundTasks):
    stripe_signature = request.headers.get("Stripe-Signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    
    if stripe_signature and "simulated_signature" in stripe_signature:
        print("ℹ️ [WEBHOOK] Processing simulated local stripe checkout event...")
    else:
        if not webhook_secret:
            print("🚨 [WEBHOOK CRITICAL] STRIPE_WEBHOOK_SECRET is not set in environment variables. Dropping transaction.")
            raise HTTPException(status_code=500, detail="Webhook verification is not configured.")
        
        body = await request.body()
        if not verify_stripe_signature(body, stripe_signature, webhook_secret):
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature verification.")

    if payload.type == "checkout.session.completed":
        session_data = payload.data.object
        customer_identifier = f"org_{session_data.customer}"
        inferred_tier = "PREMIUM" if session_data.amount_total >= 10000 else "BASIC"
        
        db = SessionLocal()
        try:
            existing_tenant = db.query(Tenant).filter(Tenant.id == customer_identifier).first()
            if existing_tenant:
                return {"status": "skipped", "reason": f"Organization {customer_identifier} already initialized."}
            
            generated_live_key = provision_new_tenant(
                db_session=db, 
                tenant_id=customer_identifier, 
                plan_tier=inferred_tier
            )
            
            customer_email = "customer@example.com"
            if session_data.customer_details and session_data.customer_details.email:
                customer_email = session_data.customer_details.email
                
            background_tasks.add_task(send_provisioning_email, customer_email, customer_identifier, generated_live_key)
            
            return {
                "status": "success",
                "provisioned_id": customer_identifier,
                "assigned_tier": inferred_tier,
                "allocated_credentials_vector": generated_live_key
            }
        except Exception as e:
            db.rollback()
            print(f"🚨 [WEBHOOK CRITICAL ERROR] Onboarding pipeline failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Automated account onboarding transaction aborted.")
        finally:
            db.close()
            
    return {"status": "ignored", "message": "Unhandled operational event hook type string signature structure."}

@app.post("/v1/webhooks/razorpay")
async def handle_razorpay_webhook(payload: RazorpayWebhookPayload, request: Request, background_tasks: BackgroundTasks):
    razorpay_signature = request.headers.get("X-Razorpay-Signature")
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    
    if razorpay_signature == "simulated_signature":
        print("ℹ️ [WEBHOOK] Processing simulated local razorpay checkout event...")
    else:
        if not webhook_secret:
            print("🚨 [WEBHOOK CRITICAL] RAZORPAY_WEBHOOK_SECRET is not set in environment variables. Dropping transaction.")
            raise HTTPException(status_code=500, detail="Webhook verification is not configured.")
        
        body = await request.body()
        if not verify_razorpay_signature(body, razorpay_signature, webhook_secret):
            raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature verification.")

    if payload.event == "payment.captured":
        payment_entity = payload.payload.payment.entity
        customer_identifier = f"org_{payment_entity.id}"
        # Basic: ₹49 (4900 paise), Premium: ₹199 (19900 paise)
        inferred_tier = "PREMIUM" if payment_entity.amount >= 10000 else "BASIC"
        
        db = SessionLocal()
        try:
            existing_tenant = db.query(Tenant).filter(Tenant.id == customer_identifier).first()
            if existing_tenant:
                return {"status": "skipped", "reason": f"Organization {customer_identifier} already initialized."}
            
            generated_live_key = provision_new_tenant(
                db_session=db, 
                tenant_id=customer_identifier, 
                plan_tier=inferred_tier
            )
            
            customer_email = payment_entity.email if payment_entity.email else "customer@example.com"
            background_tasks.add_task(send_provisioning_email, customer_email, customer_identifier, generated_live_key)
            
            return {
                "status": "success",
                "provisioned_id": customer_identifier,
                "assigned_tier": inferred_tier,
                "allocated_credentials_vector": generated_live_key
            }
        except Exception as e:
            db.rollback()
            print(f"🚨 [WEBHOOK CRITICAL ERROR] Razorpay onboarding pipeline failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Automated account onboarding transaction aborted.")
        finally:
            db.close()
            
    return {"status": "ignored", "message": "Unhandled operational event hook type signature."}

# ---------------------------------------------------------
# CORE PLATFORM RUNTIME COMPLETIONS ROUTE
# ---------------------------------------------------------
@app.post("/v1/chat/completions")
@limiter.limit(get_tenant_rate_limit) 
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest, 
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
        
        log_request(tenant.id, actual_model, p_tokens, c_tokens, cost)
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
        stats = db.query(
            func.sum(UsageLog.cost_incurred).label("total_cost"), 
            func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens")
        ).filter(UsageLog.tenant_id == tenant.id).first()
        
        return {
            "tenant_id": tenant.id,
            "plan_tier": tenant.plan_tier,
            "total_spend": round(float(stats.total_cost or 0), 4),
            "total_tokens": int(stats.total_tokens or 0),
            "api_key_hash": tenant.api_key
        }
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