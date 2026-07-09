from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

# We create a global variable, but we leave it empty (None) until initialize_sanitizer()
# runs from the app's lifespan — matches router.py's lazy-load pattern instead of
# paying this cost at import time, before the web server even boots.
analyzer = None

def initialize_sanitizer():
    """This function will be called AFTER the web server boots (mirrors router.initialize_router)."""
    global analyzer
    print("🛡️ [SYSTEM] Configuring PII Sanitizer Shield...")

    # 1. Force Presidio to use the lightweight 'sm' model instead of downloading the 'lg' model
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }

    # 2. Apply the configuration
    provider = NlpEngineProvider(nlp_configuration=configuration)
    nlp_engine_custom = provider.create_engine()

    # 3. Initialize the analyzer with the fast engine
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine_custom,
        supported_languages=["en"]
    )
    print("✅ [SYSTEM] PII Sanitizer Shield Online.")

def sanitize_prompt(text: str) -> str:
    """Scans text for sensitive PII and redacts it cleanly."""
    if not text.strip():
        return text
        
    results = analyzer.analyze(
        text=text,
        language="en",
        entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "CRYPTO", "US_SSN", "IN_PAN", "IN_AADHAAR"]
    )
    
    mutated_text = text
    for entity in sorted(results, key=lambda x: x.start, reverse=True):
        placeholder = f"[{entity.entity_type}]"
        mutated_text = mutated_text[:entity.start] + placeholder + mutated_text[entity.end:]
        
    return mutated_text