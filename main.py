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

from provider import inference_manager
import router
from sanitizer import sanitize_prompt

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🌐 [GATEWAY] Booting...")
    router.initialize_router()
    yield
    print("🛑 [GATEWAY] Shutting down.")

app = FastAPI(title="Hybrid Semantic Router API", lifespan=lifespan)

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
            provider=target_provider
        )
        
        async for chunk in response:
            # Handle streaming chunks differently per provider
            content = ""
            if target_provider == "groq":
                content = chunk.choices[0].delta.content or ""
            elif target_provider == "gemini":
                content = chunk.text
                
            payload = {
                "id": "chatcmpl-hybrid",
                "object": "chat.completion.chunk",
                "model": target_model,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(payload)}\n\n"
        
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
        response = await inference_manager.get_response(mapping["model"], [{"role":"user", "content": user_prompt}], mapping["provider"])
        return {"status": "success", "data": str(response.text if mapping["provider"] == "gemini" else response.choices[0].message.content)}

@app.get("/v1/analytics", dependencies=[Depends(get_api_key)])
async def get_analytics(tenant_id: str = "client_abc"):
    db = SessionLocal()
    try:
        stats = db.query(func.sum(UsageLog.cost_incurred).label("total_cost"), func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens).label("total_tokens")).filter(UsageLog.tenant_id == tenant_id).first()
        return {"tenant_id": tenant_id, "total_spend": round(float(stats.total_cost or 0), 4), "total_tokens": int(stats.total_tokens or 0)}
    finally:
        db.close()

@app.get("/v1/debug_keys", dependencies=[Depends(get_api_key)])
async def debug_keys():
    import os
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    return {
        "GROQ_API_KEY_exists": groq_key is not None,
        "GROQ_API_KEY_len": len(groq_key) if groq_key else 0,
        "GROQ_API_KEY_prefix": groq_key[:6] if groq_key else "",
        "GEMINI_API_KEY_exists": gemini_key is not None,
        "GEMINI_API_KEY_len": len(gemini_key) if gemini_key else 0,
        "GEMINI_API_KEY_prefix": gemini_key[:6] if gemini_key else "",
    }