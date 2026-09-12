"""The model catalogue: models are configuration in the database, not code.

The property that matters most is that an edit takes effect immediately -
a catalogue you have to restart the server to apply is not runtime
configuration.
"""
import pytest

from app.db.models.provider_model import ModelKind, ProviderModel
from app.db.session import SessionLocal
from app.providers.llm.factory import LLMProviderFactory
from app.services import model_catalog


@pytest.fixture(autouse=True)
def clean_catalogue():
    """Each test starts with an empty (unseeded) catalogue."""
    with SessionLocal() as db:
        db.query(ProviderModel).delete()
        db.commit()
    model_catalog.invalidate()
    yield
    with SessionLocal() as db:
        db.query(ProviderModel).delete()
        db.commit()
    model_catalog.invalidate()


def _add(client, admin_headers, **payload):
    body = {"kind": "chat", "provider": "testchat", "model_name": "new-model"}
    body.update(payload)
    response = client.post("/api/v1/admin/models", headers=admin_headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Fallback while unseeded
# ---------------------------------------------------------------------------


def test_an_empty_catalogue_falls_back_to_the_built_in_defaults(client):
    """A fresh database must not leave the application unable to answer."""
    provider = LLMProviderFactory.get_provider("testchat")
    assert provider.supported_models == ["fake-model"]


def test_the_database_wins_once_the_catalogue_has_any_row(client, admin_headers):
    """Otherwise disabling the last model would resurrect the code list."""
    _add(client, admin_headers, model_name="only-this-one")
    provider = LLMProviderFactory.get_provider("testchat")
    assert provider.supported_models == ["only-this-one"]
    assert "fake-model" not in provider.supported_models


# ---------------------------------------------------------------------------
# Edits take effect immediately
# ---------------------------------------------------------------------------


def test_adding_a_model_makes_it_usable_without_a_restart(client, admin_headers):
    provider = LLMProviderFactory.get_provider("testchat")
    _add(client, admin_headers, model_name="fake-model")
    _add(client, admin_headers, model_name="brand-new-model")

    assert "brand-new-model" in provider.supported_models
    provider.validate_model("brand-new-model")  # must not raise


def test_disabling_a_model_hides_it_immediately(client, admin_headers):
    created = _add(client, admin_headers, model_name="soon-disabled")
    provider = LLMProviderFactory.get_provider("testchat")
    assert "soon-disabled" in provider.supported_models

    response = client.patch(
        f"/api/v1/admin/models/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )
    assert response.status_code == 200
    assert "soon-disabled" not in provider.supported_models


def test_deleting_a_model_removes_it_immediately(client, admin_headers):
    created = _add(client, admin_headers, model_name="doomed")
    _add(client, admin_headers, model_name="survivor")
    provider = LLMProviderFactory.get_provider("testchat")

    client.delete(f"/api/v1/admin/models/{created['id']}", headers=admin_headers)
    assert provider.supported_models == ["survivor"]


def test_a_disabled_model_is_rejected_by_validation(client, admin_headers):
    """Hiding a model from the picker is not enough - the server must refuse
    it, or a client could still ask for it directly."""
    from app.core.exceptions import InvalidModelError

    created = _add(client, admin_headers, model_name="fake-model")
    client.patch(
        f"/api/v1/admin/models/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )

    with pytest.raises(InvalidModelError):
        LLMProviderFactory.get_provider("testchat").validate_model("fake-model")


def test_asking_with_a_disabled_model_is_refused_end_to_end(
    client, admin_headers, auth_headers, sample_pdf_bytes
):
    """A document is uploaded first on purpose.

    With an empty knowledge base the request is rejected before the model is
    ever looked at, so the test would pass without proving anything about
    the catalogue.
    """
    upload = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files=[("files", ("catalogued.pdf", sample_pdf_bytes, "application/pdf"))],
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    assert upload.status_code == 201, upload.text

    # Both models must be in the catalogue, since any row makes the database
    # authoritative for every provider.
    _add(client, admin_headers, kind="embedding", provider="testembed", model_name="fake-embed-model")
    created = _add(client, admin_headers, model_name="fake-model")

    payload = {
        "question": "anything",
        "provider": "testchat",
        "model": "fake-model",
        "embedding_provider": "testembed",
        "embedding_model": "fake-embed-model",
    }
    assert client.post("/api/v1/chat/ask", headers=auth_headers, json=payload).status_code == 200

    client.patch(
        f"/api/v1/admin/models/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )

    refused = client.post("/api/v1/chat/ask", headers=auth_headers, json=payload)
    assert refused.status_code == 400, refused.text
    assert "not supported" in refused.json()["message"].lower()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_duplicates_are_rejected(client, admin_headers):
    _add(client, admin_headers, model_name="only-once")
    response = client.post(
        "/api/v1/admin/models",
        headers=admin_headers,
        json={"kind": "chat", "provider": "testchat", "model_name": "only-once"},
    )
    assert response.status_code == 422


def test_the_same_name_may_exist_for_chat_and_embedding(client, admin_headers):
    """Different kinds are different namespaces."""
    _add(client, admin_headers, kind="chat", provider="testchat", model_name="shared-name")
    response = client.post(
        "/api/v1/admin/models",
        headers=admin_headers,
        json={"kind": "embedding", "provider": "testembed", "model_name": "shared-name"},
    )
    assert response.status_code == 201


def test_a_model_for_an_unknown_provider_is_rejected(client, admin_headers):
    """Such a row would be unreachable - nothing would ever look it up."""
    response = client.post(
        "/api/v1/admin/models",
        headers=admin_headers,
        json={"kind": "chat", "provider": "not-a-real-provider", "model_name": "x"},
    )
    assert response.status_code == 422


def test_an_unknown_kind_is_rejected(client, admin_headers):
    response = client.post(
        "/api/v1/admin/models",
        headers=admin_headers,
        json={"kind": "telepathy", "provider": "testchat", "model_name": "x"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_ordinary_users_cannot_read_the_catalogue(client, auth_headers):
    assert client.get("/api/v1/admin/models", headers=auth_headers).status_code == 403


def test_ordinary_users_cannot_add_models(client, auth_headers):
    """Adding a model changes what every user can select."""
    response = client.post(
        "/api/v1/admin/models",
        headers=auth_headers,
        json={"kind": "chat", "provider": "testchat", "model_name": "sneaky"},
    )
    assert response.status_code == 403


def test_ordinary_users_cannot_delete_models(client, auth_headers, admin_headers):
    created = _add(client, admin_headers, model_name="protected")
    assert client.delete(
        f"/api/v1/admin/models/{created['id']}", headers=auth_headers
    ).status_code == 403


# ---------------------------------------------------------------------------
# Listing and seeding
# ---------------------------------------------------------------------------


def test_the_admin_list_includes_disabled_models(client, admin_headers):
    """The editing view must show what the picker hides, or a disabled model
    could never be re-enabled."""
    created = _add(client, admin_headers, model_name="hidden")
    client.patch(
        f"/api/v1/admin/models/{created['id']}", headers=admin_headers, json={"is_enabled": False}
    )

    rows = client.get("/api/v1/admin/models", headers=admin_headers).json()["data"]
    assert any(row["model_name"] == "hidden" and not row["is_enabled"] for row in rows)


def test_the_providers_endpoint_reflects_the_catalogue(client, admin_headers, auth_headers):
    """This is what the model picker is built from."""
    _add(client, admin_headers, model_name="picker-visible")

    providers = client.get("/api/v1/providers/chat", headers=auth_headers).json()["data"]
    testchat = next(p for p in providers if p["provider"] == "testchat")
    assert testchat["models"] == ["picker-visible"]


def test_listing_can_be_filtered_by_kind(client, admin_headers):
    _add(client, admin_headers, kind="chat", provider="testchat", model_name="a-chat-model")
    _add(client, admin_headers, kind="embedding", provider="testembed", model_name="an-embed-model")

    rows = client.get("/api/v1/admin/models?kind=embedding", headers=admin_headers).json()["data"]
    assert rows and all(row["kind"] == "embedding" for row in rows)


def test_seeding_is_additive_and_repeatable(client, admin_headers):
    """Re-seeding must not duplicate rows or undo an operator's changes."""
    first = client.post("/api/v1/admin/models/seed", headers=admin_headers)
    assert first.status_code == 200
    added_first = first.json()["data"]
    assert added_first > 0

    second = client.post("/api/v1/admin/models/seed", headers=admin_headers)
    assert second.json()["data"] == 0, "re-seeding added rows a second time"


def test_seeding_does_not_re_enable_a_disabled_model(client, admin_headers):
    client.post("/api/v1/admin/models/seed", headers=admin_headers)
    rows = client.get("/api/v1/admin/models", headers=admin_headers).json()["data"]
    target = next(row for row in rows if row["model_name"] == "fake-model")

    client.patch(
        f"/api/v1/admin/models/{target['id']}", headers=admin_headers, json={"is_enabled": False}
    )
    client.post("/api/v1/admin/models/seed", headers=admin_headers)

    rows = client.get("/api/v1/admin/models", headers=admin_headers).json()["data"]
    still = next(row for row in rows if row["model_name"] == "fake-model")
    assert still["is_enabled"] is False, "seeding overrode a deliberate change"


def test_catalogue_changes_are_audited(client, admin_headers):
    created = _add(client, admin_headers, model_name="audited-model")
    events = client.get(
        "/api/v1/admin/audit", headers=admin_headers, params={"action": "model_catalogue.changed"}
    ).json()["data"]

    assert any(event["resource_id"] == created["id"] for event in events)


# ---------------------------------------------------------------------------
# No hardcoded lists remain
# ---------------------------------------------------------------------------


def test_no_provider_declares_a_hardcoded_supported_models_list():
    """Guards the point of this change.

    `default_models` is seed data and is expected; a `supported_models`
    assignment would be a model list that the database cannot override.
    """
    from pathlib import Path

    providers_dir = Path(__file__).resolve().parents[1] / "app" / "providers"
    offenders = [
        path.name
        for path in providers_dir.rglob("*.py")
        if "supported_models = " in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"hardcoded model lists found in {offenders}"
