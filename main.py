from database import SessionLocal
from database import UsageLog
from database import log_request
import os
import time
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from sqlalchemy import func

from dotenv import load_dotenv
load_dotenv()

from groq import AsyncGroq
# Import the module, not just the 'sr' variable, so we can call the init function
import router
from sanitizer import sanitize_prompt

# ---------------------------------------------------------
# 1. LIFESPAN MANAGER (The Boot Sequence Fix)
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This runs the moment Uvicorn binds the port successfully
    print("🌐 [GATEWAY] Port Bound Successfully. Triggering background AI load...")
    router.initialize_router()
    yield
    # This runs when the server shuts down
    print("🛑 [GATEWAY] Server shutting down.")

# Initialize the app with the lifespan manager
app = FastAPI(title="Hybrid Semantic Router API", lifespan=lifespan)

# --- PHOENIX TELEMETRY ---
if os.environ.get("RENDER") != "true":
    try:
        from phoenix.otel import register
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        tracer_provider = register()
        FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
        print("🛡️ Observability: Local Phoenix Telemetry Active.")
    except ImportError:
        print("⚠️ Telemetry modules not found.")
else:
    print("☁️ Cloud Environment Detected: Bypassing local Phoenix connection.")

# Initialize the async client
groq_client = AsyncGroq()

# ---------------------------------------------------------
# OpenAI-Compatible Payload Schema
# ---------------------------------------------------------
class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

# ---------------------------------------------------------
# Asynchronous Live Stream Engine
# ---------------------------------------------------------
async def generate_live_stream(user_prompt: str, target_model: str, tenant_id: str):
    try:
        subscription = await groq_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": user_prompt}],
            stream=True
        )
        
        # Track tokens manually for streaming
        p_tokens = 0
        c_tokens = 0
        
        async for chunk in subscription:
            # Capture usage if Groq provides it in the final chunk
            if chunk.usage:
                p_tokens = chunk.usage.prompt_tokens
                c_tokens = chunk.usage.completion_tokens
            
            if not chunk.choices:
                continue

            content_chunk = chunk.choices[0].delta.content or ""
            payload = {
                "id": "chatcmpl-hybrid",
                "object": "chat.completion.chunk",
                "model": target_model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": content_chunk},
                    "finish_reason": chunk.choices[0].finish_reason
                }]
            }
            yield f"data: {json.dumps(payload)}\n\n"
        
        # Calculate cost
        cost = (p_tokens * 0.05 + c_tokens * 0.08) / 1_000_000 if "8b" in target_model else (p_tokens * 0.59 + c_tokens * 0.79) / 1_000_000
        
        # LOG HERE
        log_request(tenant_id, target_model, p_tokens, c_tokens, cost)
        
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

from fastapi import Security, Depends
from fastapi.security.api_key import APIKeyHeader

API_KEY = os.environ.get("GATEWAY_API_KEY") # You will add this to Hugging Face Secrets
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(status_code=403, detail="Could not validate credentials")
# ---------------------------------------------------------
# Main Gateway Proxy Endpoint
# ---------------------------------------------------------
@app.post("/v1/chat/completions", dependencies=[Depends(get_api_key)])
async def create_chat_completion(request: ChatCompletionRequest):
    # Guard check: Ensure the router has finished loading in the background
    if router.sr is None:
        raise HTTPException(status_code=503, detail="AI Core is still booting up. Try again in 5 seconds.")

    raw_prompt = request.messages[-1].content
    user_prompt = sanitize_prompt(raw_prompt)
    
    if user_prompt != raw_prompt:
        print(f"🛡️ [PRIVACY] PII Detected! Mutated prompt to: '{user_prompt}'")
        
    start_time = time.time()
    # Now we call the global router object
    route_choice = router.sr(user_prompt)
    routing_latency = (time.time() - start_time) * 1000
    matched_route = route_choice.name if route_choice.name else "unclassified"
    
    print(f"[ROUTER] Decision: {matched_route.upper()} (Routing Overhead: {routing_latency:.2f}ms)")
    
    if matched_route == "safety_block":
        security_alert = "Request denied: This prompt violates enterprise safety policy rules."
        async def direct_block_stream():
            yield f"data: {json.dumps({'id': 'chatcmpl-block', 'object': 'chat.completion.chunk', 'model': 'security-gateway', 'choices': [{'index': 0, 'delta': {'content': security_alert}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(direct_block_stream(), media_type="text/event-stream")

    elif matched_route == "simple_chat":
        target_model = "llama-3.1-8b-instant"
    else:
        target_model = "llama-3.3-70b-versatile"

    if request.stream:
        return StreamingResponse(
            generate_live_stream(user_prompt, target_model, tenant_id="client_abc"), 
            media_type="text/event-stream"
        )
    else:
        response = await groq_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        # Calculate cost based on Groq pricing (per 1M tokens)
        # llama-3.1-8b-instant: Prompt $0.05/M, Completion $0.08/M
        # llama-3.3-70b-versatile: Prompt $0.59/M, Completion $0.79/M
        if target_model == "llama-3.1-8b-instant":
            cost = (prompt_tokens * 0.05 + completion_tokens * 0.08) / 1_000_000
        else:
            cost = (prompt_tokens * 0.59 + completion_tokens * 0.79) / 1_000_000

        log_request(
            tenant_id="client_abc",
            model=target_model,
            p_tokens=prompt_tokens,
            c_tokens=completion_tokens,
            cost=cost
        )
        return response.model_dump()

@app.get("/v1/analytics")
async def get_analytics(tenant_id: str = "client_abc"):
    db = SessionLocal()
    try:
        # Query to calculate total spend and token usage
        stats = db.query(
            func.sum(UsageLog.cost_incurred).label("total_cost"),
            func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens")
        ).filter(UsageLog.tenant_id == tenant_id).first()
        
        return {
            "tenant_id": tenant_id,
            "total_spend": round(stats.total_cost or 0, 4),
            "total_tokens": stats.total_tokens or 0
        }
    finally:
        db.close()