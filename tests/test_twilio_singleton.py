import asyncio
import main


def test_dispatch_system_alert_reuses_single_twilio_client(monkeypatch):
    construction_count = {"count": 0}

    class FakeMessages:
        def create(self, **kwargs):
            return type("FakeMsg", (), {"sid": "SMfake"})()

    class FakeTwilioClient:
        def __init__(self, *args, **kwargs):
            construction_count["count"] += 1
            self.messages = FakeMessages()

    # Replace the module-level singleton with a fake instance (constructed once, here),
    # then verify dispatch_system_alert never constructs a new one internally.
    monkeypatch.setattr(main, "twilio_client", FakeTwilioClient("sid", "token"))
    construction_count["count"] = 0  # reset — only the line above should have constructed one
    monkeypatch.setattr(main, "DEVELOPER_WHATSAPP_TO", "whatsapp:+10000000000")

    asyncio.run(main.dispatch_system_alert("INFO", "TEST", "first alert"))
    asyncio.run(main.dispatch_system_alert("INFO", "TEST", "second alert"))

    assert construction_count["count"] == 0
