# provider.py
import os
from google import genai
from groq import AsyncGroq

class InferenceManager:
    def __init__(self):
        groq_key = os.environ.get("GROQ_API_KEY", "").strip() or None
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or None
        
        self.groq_client = AsyncGroq(api_key=groq_key)
        self.gemini_client = genai.Client(api_key=gemini_key, http_options={"api_version": "v1"})
        
        # Define the fallback chain
        self.fallback_chain = {
            "groq": "gemini",
            "gemini": None  # End of the line
        }

    async def get_response(self, model_name, messages, provider, fallback_provider="gemini", stream=True):
        """Attempts the primary provider, falls back dynamically if it crashes."""
        try:
            res = await self._call_provider(model_name, messages, provider, stream)
            actual_model = "gemini-2.5-flash" if (provider == "gemini" and "llama" in model_name) else model_name
            return res, provider, actual_model
        except Exception as e:
            primary_error = e
            fallback = fallback_provider if provider != fallback_provider else None
            
            if fallback:
                print(f"⚠️ [FAILOVER ENGINE] {provider} failed: {primary_error}. Routing backup to {fallback}...")
                try:
                    res = await self._call_provider(model_name, messages, fallback, stream)
                    actual_model = "gemini-2.5-flash" if (fallback == "gemini" and "llama" in model_name) else model_name
                    return res, fallback, actual_model
                except Exception as fallback_error:
                    raise RuntimeError(
                        f"Primary provider ({provider}) failed: {primary_error}. "
                        f"Failover provider ({fallback}) failed: {fallback_error}."
                    )
            else:
                raise e

    async def _call_provider(self, model_name, messages, provider, stream=True):
        if provider == "groq":
            return await self.groq_client.chat.completions.create(
                model=model_name, messages=messages, stream=stream
            )
        elif provider == "gemini":
            gemini_model_name = "gemini-2.5-flash" if "llama" in model_name else model_name
            if stream:
                return await self.gemini_client.aio.models.generate_content_stream(
                    model=gemini_model_name,
                    contents=messages[-1]['content']
                )
            else:
                return await self.gemini_client.aio.models.generate_content(
                    model=gemini_model_name,
                    contents=messages[-1]['content']
                )
        else:
            raise ValueError(f"Provider {provider} not supported.")

inference_manager = InferenceManager()