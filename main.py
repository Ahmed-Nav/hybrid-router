from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, UsageLog, log_request, Tenant, hash_api_key
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

    # Tier Enforcement: Non-premium tenants cannot access advanced inference models.
    # We automatically demote their route to the basic track unless they explicitly requested a premium model.
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