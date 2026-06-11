# provider.py
import os
import google.generativeai as genai
from groq import AsyncGroq

class InferenceManager:
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        
        # Define the fallback chain
        self.fallback_chain = {
            "groq": "gemini",
            "gemini": None  # End of the line
        }

    async def get_response(self, model_name, messages, provider):
        """Attempts the primary provider, falls back if it fails."""
        try:
            return await self._call_provider(model_name, messages, provider)
        except Exception as e:
            primary_error = e
            fallback = self.fallback_chain.get(provider)
            if fallback:
                print(f"⚠️ [FAILOVER] {provider} failed: {primary_error}. Switching to {fallback}...")
                try:
                    return await self._call_provider(model_name, messages, fallback)
                except Exception as fallback_error:
                    raise RuntimeError(
                        f"Primary provider ({provider}) failed: {primary_error}. "
                        f"Failover provider ({fallback}) failed: {fallback_error}."
                    )
            else:
                raise e

    async def _call_provider(self, model_name, messages, provider):
        if provider == "groq":
            return await self.groq_client.chat.completions.create(
                model=model_name, messages=messages, stream=True
            )
        elif provider == "gemini":
            gemini_model_name = "gemini-1.5-flash" if "llama" in model_name else model_name
            model = genai.GenerativeModel(gemini_model_name)
            return await model.generate_content_async(messages[-1]['content'], stream=True)
        else:
            raise ValueError(f"Provider {provider} not supported.")

inference_manager = InferenceManager()