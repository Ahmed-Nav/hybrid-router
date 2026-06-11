from database import SessionLocal, UsageLog, log_request
import os
import time
import json
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from sqlalchemy import func
from dotenv import load_dotenv

load_dotenv()

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# 1. Create Limiter
limiter = Limiter(key_func=get_remote_address)

from provider import inference_manager
import router
from sanitizer import sanitize_prompt

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🌐 [GATEWAY] Booting...")
    router.initialize_router()
    yield
    print("🛑 [GATEWAY] Shutting down.")

# 2. Instantiate FastAPI
app = FastAPI(title="Hybrid Semantic Router API", lifespan=lifespan)

# 3. Configure Rate Limiter
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

async def generate_live_stream(user_prompt: str, target_model: str, target_provider: str, tenant_id: str):
    try:
        # Use the dynamic provider manager
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
                # Groq / OpenAI format
                actual_provider = "groq"
                actual_model = target_model
                if getattr(chunk, "usage", None):
                    p_tokens = chunk.usage.prompt_tokens
                    c_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content or ""
            else:
                # Gemini format
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
        
        # Calculate cost based on actual provider and model
        if actual_provider == "groq":
            cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in actual_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        else: # gemini
            cost = (p_tokens * 0.075 + c_tokens * 0.30) / 1_000_000
            
        log_request(tenant_id, actual_model, p_tokens, c_tokens, cost)
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

API_KEY = os.environ.get("GATEWAY_API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_api_key(key: str = Security(api_key_header)):
    if key == API_KEY: return key
    raise HTTPException(status_code=403, detail="Invalid credentials")

@app.post("/v1/chat/completions", dependencies=[Depends(get_api_key)])
@limiter.limit("5/minute")
async def create_chat_completion(request: ChatCompletionRequest):
    if router.sr is None:
        raise HTTPException(status_code=503, detail="AI Core booting...")

    user_prompt = sanitize_prompt(request.messages[-1].content)
    route_choice = router.sr(user_prompt)
    matched_route = route_choice.name if route_choice.name else "complex_reasoning"
    
    # DYNAMIC CONFIG LOOKUP
    mapping = router.MODEL_MAPPINGS.get(matched_route, {"model": "llama-3.3-70b-versatile", "provider": "groq"})
    
    if matched_route == "safety_block":
        return StreamingResponse(iter(["data: [BLOCKED]\n\n"]), media_type="text/event-stream")

    if request.stream:
        return StreamingResponse(
            generate_live_stream(user_prompt, mapping["model"], mapping["provider"], "client_abc"), 
            media_type="text/event-stream"
        )
    else:
        # Standard non-streamed response
        response = await inference_manager.get_response(
            model_name=mapping["model"], 
            messages=[{"role":"user", "content": user_prompt}], 
            provider=mapping["provider"],
            stream=False
        )
        
        # Safely parse the response depending on what object was returned
        if hasattr(response, "choices"):
            # Groq
            data_content = response.choices[0].message.content
            p_tokens = response.usage.prompt_tokens if getattr(response, "usage", None) else 0
            c_tokens = response.usage.completion_tokens if getattr(response, "usage", None) else 0
            actual_model = mapping["model"]
            cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in actual_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        else:
            # Gemini
            data_content = response.text
            p_tokens = response.usage_metadata.prompt_token_count if getattr(response, "usage_metadata", None) else 0
            c_tokens = response.usage_metadata.candidates_token_count if getattr(response, "usage_metadata", None) else 0
            actual_model = "gemini-2.5-flash" if "llama" in mapping["model"] else mapping["model"]
            cost = (p_tokens * 0.075 + c_tokens * 0.30) / 1_000_000
            
        log_request("client_abc", actual_model, p_tokens, c_tokens, cost)
        return {"status": "success", "data": str(data_content)}

@app.get("/v1/analytics", dependencies=[Depends(get_api_key)])
@limiter.limit("5/minute")
async def get_analytics(tenant_id: str = "client_abc"):
    db = SessionLocal()
    try:
        stats = db.query(func.sum(UsageLog.cost_incurred).label("total_cost"), func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens")).filter(UsageLog.tenant_id == tenant_id).first()
        return {"tenant_id": tenant_id, "total_spend": round(float(stats.total_cost or 0), 4), "total_tokens": int(stats.total_tokens or 0)}
    finally:
        db.close()