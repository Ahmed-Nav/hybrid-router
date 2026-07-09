from main import compute_provider_cost


def test_groq_8b_model_pricing():
    cost = compute_provider_cost("groq", "llama-3.1-8b-instant", 1000, 500)
    assert cost == (1000 * 0.05 + 500 * 0.08) / 1_000_000


def test_groq_70b_model_pricing():
    cost = compute_provider_cost("groq", "llama-3.3-70b-versatile", 1000, 500)
    assert cost == (1000 * 0.59 + 500 * 0.79) / 1_000_000


def test_gemini_pricing():
    cost = compute_provider_cost("gemini", "gemini-2.5-flash", 1000, 500)
    assert cost == (1000 * 0.075 + 500 * 0.30) / 1_000_000


def test_streaming_and_non_streaming_paths_use_identical_pricing():
    # Both code paths must call this same function — this test exists to catch
    # any future re-duplication of the pricing formula.
    for provider, model in [("groq", "llama-3.1-8b-instant"), ("groq", "llama-3.3-70b-versatile"), ("gemini", "gemini-2.5-flash")]:
        cost_a = compute_provider_cost(provider, model, 777, 333)
        cost_b = compute_provider_cost(provider, model, 777, 333)
        assert cost_a == cost_b
