import os
import time
import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

# Load environment variables securely from the .env file
from dotenv import load_dotenv
load_dotenv()

# Import the official asynchronous Groq client library
from groq import AsyncGroq

# Import the components we engineered in Phase 1
from router import sr
from sanitizer import sanitize_prompt

app = FastAPI(title="Hybrid Semantic Router API (Production Phase 3)")

if os.environ.get("RENDER") != "true":
    try:
        from phoenix.otel import register
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        
        # Start the local Phoenix server connection
        tracer_provider = register()
        
        # Instrument FastAPI to automatically trace all incoming requests
        FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
        print("🛡️ Observability: Local Phoenix Telemetry Active.")
    except ImportError:
        print("⚠️ Telemetry modules not found. Running without observability.")
else:
    print("☁️ Cloud Environment Detected: Bypassing local Phoenix connection.")

# Initialize the async client; it automatically looks for the GROQ_API_KEY env variable
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
async def generate_live_stream(user_prompt: str, target_model: str):
    """Establishes an upstream connection to Groq and streams chunks down to the client."""
    try:
        # Connect to Groq's chat completions stream asynchronously
        subscription = await groq_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": user_prompt}],
            stream=True
        )

        # Loop over incoming stream chunks asynchronously from Groq's servers
        async for chunk in subscription:
            content_chunk = chunk.choices[0].delta.content or ""
            
            # Format the incoming token precisely to match OpenAI streaming chunk structures
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
            
        yield "data: [DONE]\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

# ---------------------------------------------------------
# Main Gateway Proxy Endpoint
# ---------------------------------------------------------
@app.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest):
    raw_prompt = request.messages[-1].content
    
    # 1. Run the prompt through our Privacy Shield first
    user_prompt = sanitize_prompt(raw_prompt)
    if user_prompt != raw_prompt:
        print(f"🛡️ [PRIVACY] PII Detected! Mutated prompt to: '{user_prompt}'")
        
    # 2. Extract classification via Semantic Router
    start_time = time.time()
    route_choice = sr(user_prompt)
    routing_latency = (time.time() - start_time) * 1000
    matched_route = route_choice.name if route_choice.name else "unclassified"
    
    print(f"[ROUTER] Decision: {matched_route.upper()} (Routing Overhead: {routing_latency:.2f}ms)")
    
    # 3. Execution Forking Logic
    if matched_route == "safety_block":
        # Intercept instantly, bypassing upstream models to save costs
        security_alert = "Request denied: This prompt violates enterprise safety policy rules."
        
        async def direct_block_stream():
            yield f"data: {json.dumps({'id': 'chatcmpl-block', 'object': 'chat.completion.chunk', 'model': 'security-gateway', 'choices': [{'index': 0, 'delta': {'content': security_alert}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"
            
        return StreamingResponse(direct_block_stream(), media_type="text/event-stream")

    elif matched_route == "simple_chat":
        # Route to the fast, low-cost model
        target_model = "llama-3.1-8b-instant"
    else:
        # Route deep logic or unclassified code blocks to the premium powerhouse model
        target_model = "llama-3.3-70b-versatile"

    print(f"📡 [GATEWAY] Forking traffic over to Groq Infrastructure -> Model: {target_model}")

    # 4. Handle Live Response Delivery
    if request.stream:
        return StreamingResponse(
            generate_live_stream(user_prompt, target_model), 
            media_type="text/event-stream"
        )
    else:
        # Clean synchronous processing block for non-streaming requests
        response = await groq_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": user_prompt}]
        )
        return response.model_dump()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)