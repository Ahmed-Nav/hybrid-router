import main


def test_x_forwarded_for_ignored_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)

    class FakeClient:
        host = "10.0.0.5"

    class FakeRequest:
        headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
        client = FakeClient()

    key = main.get_rate_limit_key(FakeRequest())
    assert key == "10.0.0.5"


def test_x_forwarded_for_trusted_when_env_var_set(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")

    class FakeClient:
        host = "10.0.0.5"

    class FakeRequest:
        headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
        client = FakeClient()

    key = main.get_rate_limit_key(FakeRequest())
    assert key == "203.0.113.9"
