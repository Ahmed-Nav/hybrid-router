from presidio_analyzer import AnalyzerEngine

print("🛡️ [SYSTEM] Initializing PII Sanitizer Shield...")
# Initialize the local Presidio engine
analyzer = AnalyzerEngine()

def sanitize_prompt(text: str) -> str:
    """Scans text for sensitive PII and redacts it cleanly."""
    if not text.strip():
        return text
        
    # Analyze the text for entities like EMAIL, PHONE_NUMBER, CREDIT_CARD, PERSON
    results = analyzer.analyze(
        text=text, 
        language="en", 
        entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "CRYPTO", "US_SSN"]
    )
    
    # Sort results backward to mutate the string from tail to head without messing up indexes
    mutated_text = text
    for entity in sorted(results, key=lambda x: x.start, reverse=True):
        placeholder = f"[{entity.entity_type}]"
        mutated_text = mutated_text[:entity.start] + placeholder + mutated_text[entity.end:]
        
    return mutated_text

# Quick verification test
if __name__ == "__main__":
    test_leak = "My email is developer@example.com and my phone number is 123-456-7890."
    print("\n--- 🛡️ TESTING PII SANITIZATION ---")
    print(f"Original: {test_leak}")
    print(f"Sanitized: {sanitize_prompt(test_leak)}")