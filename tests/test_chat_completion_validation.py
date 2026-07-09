from database import provision_new_tenant


def test_empty_messages_rejected(client, db_session):
    raw_key = provision_new_tenant(db_session, "org_empty_msgs_test", "BASIC")

    resp = client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": raw_key},
        json={"model": "hybrid-gateway", "messages": []},
    )
    assert resp.status_code == 422


def test_oversized_prompt_rejected(client, db_session):
    raw_key = provision_new_tenant(db_session, "org_oversized_prompt_test", "BASIC")

    huge_prompt = "a" * 20001
    resp = client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": raw_key},
        json={"model": "hybrid-gateway", "messages": [{"role": "user", "content": huge_prompt}]},
    )
    assert resp.status_code == 413
