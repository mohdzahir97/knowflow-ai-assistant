"""Document-scoped chat: the ADMIN document-testing capability.

Admins verify a freshly uploaded document is indexed and retrievable by
conversing with that document alone. End users have no equivalent - they
never select, or learn of, the documents behind an answer - so the tests at
the bottom assert that an ordinary account is refused server-side.
"""


def _upload_sample(client, headers, sample_pdf_bytes, filename="sample.pdf"):
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": (filename, sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    return response.json()["data"][0]["id"]


def _ask(client, headers, question, **overrides):
    payload = {"question": question, "provider": "testchat", "model": "fake-model"}
    payload.update(overrides)
    return client.post("/api/v1/chat/ask", headers=headers, json=payload)


def test_document_chat_starts_empty(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    response = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_document_scoped_ask_does_not_require_embedding_fields(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    response = _ask(client, admin_headers, "How many days of paid leave do employees get?", document_id=document_id)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["document_id"] == document_id
    assert "20 days" in data["answer"]


def test_document_scoped_ask_reuses_the_same_session(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    first = _ask(client, admin_headers, "How many days of paid leave?", document_id=document_id).json()["data"]
    second = _ask(client, admin_headers, "How is it accrued?", document_id=document_id).json()["data"]
    assert first["session_id"] == second["session_id"]

    history = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert len(history["messages"]) == 4  # 2 turns x (user + assistant)


def test_two_documents_have_independent_chat_histories(client, admin_headers, sample_pdf_bytes):
    doc_a = _upload_sample(client, admin_headers, sample_pdf_bytes, filename="doc_a.pdf")
    doc_b = _upload_sample(client, admin_headers, sample_pdf_bytes, filename="doc_b.pdf")

    _ask(client, admin_headers, "Question about A", document_id=doc_a)
    _ask(client, admin_headers, "Question about B", document_id=doc_b)
    _ask(client, admin_headers, "Second question about A", document_id=doc_a)

    history_a = client.get(f"/api/v1/chat/documents/{doc_a}", headers=admin_headers).json()["data"]
    history_b = client.get(f"/api/v1/chat/documents/{doc_b}", headers=admin_headers).json()["data"]

    assert len(history_a["messages"]) == 4  # 2 turns
    assert len(history_b["messages"]) == 2  # 1 turn
    assert history_a["id"] != history_b["id"]
    assert all(m["content"] != "Question about B" for m in history_a["messages"])
    assert all(m["content"] != "Question about A" and m["content"] != "Second question about A" for m in history_b["messages"])


def test_clear_document_chat_history(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    _ask(client, admin_headers, "How many days of paid leave?", document_id=document_id)

    response = client.delete(f"/api/v1/chat/documents/{document_id}", headers=admin_headers)
    assert response.status_code == 200

    history = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert history is None


def test_clear_document_chat_history_is_idempotent(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    response = client.delete(f"/api/v1/chat/documents/{document_id}", headers=admin_headers)
    assert response.status_code == 200


def test_delete_individual_message(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    _ask(client, admin_headers, "How many days of paid leave?", document_id=document_id)

    history = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert len(history["messages"]) == 2
    message_id_to_delete = history["messages"][0]["id"]

    response = client.delete(f"/api/v1/chat/messages/{message_id_to_delete}", headers=admin_headers)
    assert response.status_code == 200

    history_after = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert len(history_after["messages"]) == 1
    assert all(m["id"] != message_id_to_delete for m in history_after["messages"])


def test_end_user_cannot_use_document_scoped_chat(client, admin_headers, auth_headers, sample_pdf_bytes):
    """End users must not be able to target a document, even by guessing an
    id - selecting the corpus is an admin capability and is refused
    server-side rather than merely hidden."""
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)

    assert _ask(client, auth_headers, "test", document_id=document_id).status_code == 403
    assert client.get(f"/api/v1/chat/documents/{document_id}", headers=auth_headers).status_code == 403
    assert client.delete(f"/api/v1/chat/documents/{document_id}", headers=auth_headers).status_code == 403


def test_deleting_a_message_owned_by_another_user_is_rejected(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    _ask(client, admin_headers, "How many days of paid leave?", document_id=document_id)
    history = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    message_id = history["messages"][0]["id"]

    other_email = "other-message-delete-user@example.com"
    client.post("/api/v1/auth/register", json={"email": other_email, "password": "password123"})
    login = client.post("/api/v1/auth/login", json={"email": other_email, "password": "password123"})
    other_headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    response = client.delete(f"/api/v1/chat/messages/{message_id}", headers=other_headers)
    assert response.status_code == 404

    # The message must still exist for its actual owner.
    history_after = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert any(m["id"] == message_id for m in history_after["messages"])


def test_deleting_document_cascades_its_chat_history(client, admin_headers, sample_pdf_bytes):
    document_id = _upload_sample(client, admin_headers, sample_pdf_bytes)
    _ask(client, admin_headers, "How many days of paid leave?", document_id=document_id)

    response = client.delete(f"/api/v1/documents/{document_id}", headers=admin_headers)
    assert response.status_code == 200

    history = client.get(f"/api/v1/chat/documents/{document_id}", headers=admin_headers).json()["data"]
    assert history is None


def test_general_chat_still_requires_embedding_fields(client, admin_headers, sample_pdf_bytes):
    _upload_sample(client, admin_headers, sample_pdf_bytes)
    response = _ask(client, admin_headers, "How many days of paid leave?")
    assert response.status_code == 422
