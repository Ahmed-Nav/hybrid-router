from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, UsageLog, log_request, Tenant, hash_api_key, provision_new_tenant
import os
import time
import json
from fastapi import FastAPI, HTTPException, Security, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from sqlalchemy import func

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import jwt
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
from database import User, hash_password

def get_rate_limit_key(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return hash_api_key(api_key) # Limit by fingerprint safely
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
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

async def generate_live_stream(user_prompt: str, target_model: str, target_provider: str, fallback_provider: str, tenant_id: str):
    try:
        response = await inference_manager.get_response(
            model_name=target_model,
            messages=[{"role": "user", "content": user_prompt}],
            provider=target_provider,
            stream=True
        )
        
        p_tokens = 0
        c_tokens = 0
        actual_provider = target_provider
        actual_model = target_model
        
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

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_authenticated_tenant(key: str = Security(api_key_header)):
    db = SessionLocal()
    try:
        hashed_key = hash_api_key(key)
        tenant = db.query(Tenant).filter(Tenant.api_key == hashed_key, Tenant.is_active == True).first()
        if not tenant:
            raise HTTPException(status_code=403, detail="Invalid or deactivated credentials.")
        return tenant
    finally:
        db.close()

JWT_SECRET = os.environ.get("JWT_SECRET", "SUPER_SECRET_NEOBRUTALIST_KEY_2026")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

class LoginRequest(BaseModel):
    username: str
    password: str

class StripeCustomer(BaseModel):
    id: str
    email: str
    description: Optional[str] = None

class StripeObject(BaseModel):
    customer: str
    amount_total: int
    currency: str
    custom_fields: Optional[List[dict]] = None

class StripeData(BaseModel):
    object: StripeObject

class StripeWebhookPayload(BaseModel):
    id: str
    type: str
    data: StripeData

# ---------------------------------------------------------
# NEW: UN-AUTHENTICATED STRIPE WEBHOOK INGESTION ENGINE
# ---------------------------------------------------------
@app.post("/v1/webhooks/stripe")
async def handle_stripe_billing_webhook(payload: StripeWebhookPayload, request: Request):
    """
    Asynchronous transaction processing node that listens to 
    successful checkout events to scale provisioning automatically.
    """
    # Security Validation Guard (Simulating Stripe Signature Check)
    stripe_signature = request.headers.get("Stripe-Signature")
    if not stripe_signature:
        # For development validation; switch to strict enforcement in production cloud environments
        print("⚠️ [WEBHOOK WARNING] Inbound webhook event arrived without explicit validation signature header.")

    # Process only successful checkout sessions
    if payload.type == "checkout.session.completed":
        session_data = payload.data.object
        
        # Determine organizational parameters from metadata or customer tags
        # For testing automation, convert standard customer emails into structured IDs safely
        customer_identifier = f"org_{payload.id[:8]}"
        
        # Infer plan tier levels using invoice financial thresholds (e.g., $100+ matches Premium)
        inferred_tier = "PREMIUM" if session_data.amount_total >= 10000 else "BASIC"
        
        db = SessionLocal()
        try:
            # Check if tenant exists to prevent transaction unique constraints collisions
            existing_tenant = db.query(Tenant).filter(Tenant.id == customer_identifier).first()
            if existing_tenant:
                return {"status": "skipped", "reason": f"Organization {customer_identifier} already initialized."}
            
            # Programmatically provision infrastructure records and retrieve raw key strings
            generated_live_key = provision_new_tenant(
                db_session=db, 
                tenant_id=customer_identifier, 
                plan_tier=inferred_tier
            )
            
            # -----------------------------------------------------------------
            # ENTERPRISE EXTENSION NOTE: (Task 6.3 Notification Loop Hook)
            # This is exactly where you invoke background mail task clients 
            # (e.g., SendGrid/Boto3 SES) to dispatch the live token:
            # print(f"✉️ Outbound Welcome Mail transmitted containing key: {generated_live_key}")
            # -----------------------------------------------------------------
            
            return {
                "status": "success",
                "provisioned_id": customer_identifier,
                "assigned_tier": inferred_tier,
                "allocated_credentials_vector": generated_live_key
            }
            
        except Exception as e:
            db.rollback()
            print(f"🚨 [WEBHOOK CRITICAL ERROR] Pipeline failed programmatically processing order tracking data: {str(e)}")
            raise HTTPException(status_code=500, detail="Automated account onboarding transaction aborted.")
        finally:
            db.close()
            
    return {"status": "ignored", "message": "Unhandled operational event hook type string signature structure."}

@app.post("/v1/auth/login")
async def login_dashboard_session(payload: LoginRequest):
    db = SessionLocal()
    try:
        # 1. Encrypt incoming password to compare with database hash
        incoming_hash = hash_password(payload.password)
        
        # 2. Query matching identity
        user = db.query(User).filter(
            User.username == payload.username,
            User.password_hash == incoming_hash
        ).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid operator identity or password alignment.")
        
        # 3. Construct JWT Payload with explicit claims
        token_expiry = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_claims = {
            "sub": user.username,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "exp": token_expiry
        }
        
        # 4. Sign token cryptographically
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

@app.post("/v1/chat/completions")
@limiter.limit("60/minute") 
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
        response = await inference_manager.get_response(
            model_name=mapping["model"],
            messages=[{"role": "user", "content": user_prompt}],
            provider=mapping["provider"],
            fallback_provider=tenant.fallback_provider, # Added
            stream=False
        )
        
        if hasattr(response, "choices"):
            content = response.choices[0].message.content
            p_tokens = response.usage.prompt_tokens if getattr(response, "usage", None) else 0
            c_tokens = response.usage.completion_tokens if getattr(response, "usage", None) else 0
            actual_model = mapping["model"]
            cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in actual_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        else:
            content = response.text
            p_tokens = response.usage_metadata.prompt_token_count if getattr(response, "usage_metadata", None) else 0
            c_tokens = response.usage_metadata.candidates_token_count if getattr(response, "usage_metadata", None) else 0
            actual_model = "gemini-2.5-flash" if "llama" in mapping["model"] else mapping["model"]
            cost = (p_tokens * 0.075 + c_tokens * 0.30) / 1_000_000
            
        log_request(tenant.id, actual_model, p_tokens, c_tokens, cost)
        return {"status": "success", "data": str(content)}

@app.get("/v1/analytics")
async def get_analytics(tenant: Tenant = Depends(get_authenticated_tenant)):
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
            "total_tokens": int(stats.total_tokens or 0)
        }
    finally:
        db.close()