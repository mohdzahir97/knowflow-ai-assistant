def test_health_check_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["api_status"] == "ok"
    assert "version" in data
    assert data["chromadb_status"] == "ok"
    assert "testchat" in data["chat_providers"]
    assert "testembed" in data["embedding_providers"]


def test_health_check_does_not_require_authentication(client):
    response = client.get("/health")
    assert response.status_code == 200
