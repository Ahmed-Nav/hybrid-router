import main
from database import provision_new_tenant, UsageLog


class FakeRouteChoice:
    name = "simple_chat"


class FakeRouterModule:
    sr = staticmethod(lambda prompt: FakeRouteChoice())
    MODEL_MAPPINGS = {"simple_chat": {"model": "llama-3.1-8b-instant", "provider": "groq"}}


class FakeUsageMetadata:
    prompt_token_count = 50
    candidates_token_count = 20


class FakeGeminiChunk:
    text = "hello"
    usage_metadata = FakeUsageMetadata()


async def fake_gemini_stream():
    yield FakeGeminiChunk()


def test_streaming_request_records_fallback_when_provider_switches(client, db_session, monkeypatch):
    raw_key = provision_new_tenant(db_session, "org_stream_fallback_test", "PREMIUM")

    async def fake_get_response(model_name, messages, provider, fallback_provider, stream):
        # Simulate the primary provider (groq) failing over to gemini.
        return fake_gemini_stream(), "gemini", model_name

    monkeypatch.setattr(main, "router", FakeRouterModule())
    monkeypatch.setattr(main.inference_manager, "get_response", fake_get_response)

    resp = client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": raw_key},
        json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert resp.status_code == 200

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_stream_fallback_test").order_by(UsageLog.id.desc()).first()
    assert log is not None
    assert log.used_fallback is True
    assert log.prompt_tokens == 50
    assert log.completion_tokens == 20


def test_streaming_request_records_tier_capped_flag(client, db_session, monkeypatch):
    raw_key = provision_new_tenant(db_session, "org_stream_tier_capped_test", "BASIC")

    class TieredRouteChoice:
        name = "complex_reasoning"

    class TieredRouterModule:
        sr = staticmethod(lambda prompt: TieredRouteChoice())
        MODEL_MAPPINGS = {
            "complex_reasoning": {"model": "llama-3.3-70b-versatile", "provider": "groq"},
            "simple_chat": {"model": "llama-3.1-8b-instant", "provider": "groq"},
        }

    async def fake_get_response(model_name, messages, provider, fallback_provider, stream):
        return fake_gemini_stream(), provider, model_name

    monkeypatch.setattr(main, "router", TieredRouterModule())
    monkeypatch.setattr(main.inference_manager, "get_response", fake_get_response)

    resp = client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": raw_key},
        json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": "write a recursive function"}], "stream": True},
    )
    assert resp.status_code == 200

    log = db_session.query(UsageLog).filter(UsageLog.tenant_id == "org_stream_tier_capped_test").order_by(UsageLog.id.desc()).first()
    assert log is not None
    assert log.was_tier_capped is True
