def _upload_sample(client, headers, sample_pdf_bytes):
    return client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )


def _ask(client, headers, question, **overrides):
    payload = {
        "question": question,
        "provider": "testchat",
        "model": "fake-model",
        "embedding_provider": "testembed",
        "embedding_model": "fake-embed-model",
    }
    payload.update(overrides)
    return client.post("/api/v1/chat/ask", headers=headers, json=payload)


def test_ask_without_documents_returns_404(client, auth_headers):
    response = _ask(client, auth_headers, "How many paid leave days?")
    assert response.status_code == 404


def test_ask_returns_answer_with_citations(client, auth_headers, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)

    response = _ask(client, auth_headers, "How many days of paid leave do employees get?")
    assert response.status_code == 200

    data = response.json()["data"]
    assert "20 days" in data["answer"]
    assert len(data["sources"]) > 0
    assert data["sources"][0]["document"] == "sample.pdf"
    assert data["token_usage"]["total_tokens"] == 50


def test_ask_irrelevant_question_returns_fallback_message(client, auth_headers, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)

    response = _ask(client, auth_headers, "What is the airspeed velocity of an unladen swallow?")
    assert response.status_code == 200
    assert "couldn't find" in response.json()["data"]["answer"].lower()


def test_ask_invalid_provider_returns_400(client, auth_headers, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)

    response = _ask(client, auth_headers, "test", provider="does-not-exist")
    assert response.status_code == 400


def test_ask_requires_authentication(client, sample_pdf_bytes):
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "question": "test",
            "provider": "testchat",
            "model": "fake-model",
            "embedding_provider": "testembed",
            "embedding_model": "fake-embed-model",
        },
    )
    assert response.status_code == 401


def test_chat_session_persists_conversation_history(client, auth_headers, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)

    first = _ask(client, auth_headers, "How many days of paid leave do employees get?").json()["data"]
    session_id = first["session_id"]

    _ask(client, auth_headers, "And how is it accrued?", session_id=session_id)

    response = client.get(f"/api/v1/chat/sessions/{session_id}", headers=auth_headers)
    assert response.status_code == 200
    messages = response.json()["data"]["messages"]
    assert len(messages) == 4  # 2 user + 2 assistant


def test_chat_sessions_are_isolated_per_user(client, auth_headers, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)
    session_id = _ask(client, auth_headers, "How many days of paid leave do employees get?").json()["data"]["session_id"]

    other_email = "other-chat-user@example.com"
    client.post("/api/v1/auth/register", json={"email": other_email, "password": "password123"})
    login = client.post("/api/v1/auth/login", json={"email": other_email, "password": "password123"})
    other_headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    response = client.get(f"/api/v1/chat/sessions/{session_id}", headers=other_headers)
    assert response.status_code == 404
