"""Projects, chat organisation, and - most importantly - resource ownership.

The organisational features are straightforward. The tests that matter are
the ownership ones: a user must never reach another user's project or chat
by supplying its id, however the id was obtained.
"""
import uuid

import pytest

from tests.conftest import _register_and_login


@pytest.fixture
def other_user(client):
    """A second, unrelated account for isolation checks."""
    return _register_and_login(client, f"other-{uuid.uuid4().hex[:10]}@example.com")


def _create_project(client, headers, name="Banking"):
    response = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _start_chat(client, headers, admin_headers, sample_pdf_bytes, question="First question"):
    """Ask something so a chat session exists to organise."""
    client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files={"files": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    response = client.post(
        "/api/v1/chat/ask",
        headers=headers,
        json={
            "question": question,
            "provider": "testchat",
            "model": "fake-model",
            "embedding_provider": "testembed",
            "embedding_model": "fake-embed-model",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["session_id"]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_create_and_list_projects(client, auth_headers):
    _create_project(client, auth_headers, "Banking")
    _create_project(client, auth_headers, "Interview Prep")

    projects = client.get("/api/v1/projects", headers=auth_headers).json()["data"]
    assert {p["name"] for p in projects} == {"Banking", "Interview Prep"}
    assert all(p["chat_count"] == 0 for p in projects)


def test_duplicate_project_name_rejected(client, auth_headers):
    _create_project(client, auth_headers, "Banking")
    response = client.post("/api/v1/projects", headers=auth_headers, json={"name": "Banking"})
    assert response.status_code == 422


def test_blank_project_name_rejected(client, auth_headers):
    """Whitespace passes a min_length check but renders as an unusable name."""
    response = client.post("/api/v1/projects", headers=auth_headers, json={"name": "   "})
    assert response.status_code == 422


def test_two_users_may_reuse_the_same_project_name(client, auth_headers, other_user):
    """Uniqueness is per user, not global."""
    _create_project(client, auth_headers, "Banking")
    _create_project(client, other_user, "Banking")


def test_rename_project(client, auth_headers):
    project = _create_project(client, auth_headers, "Old name")
    response = client.patch(
        f"/api/v1/projects/{project['id']}", headers=auth_headers, json={"name": "New name"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "New name"


# ---------------------------------------------------------------------------
# Chat organisation
# ---------------------------------------------------------------------------


def test_move_chat_into_and_out_of_a_project(client, auth_headers, admin_headers, sample_pdf_bytes):
    chat_id = _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes)
    project = _create_project(client, auth_headers)

    moved = client.patch(
        f"/api/v1/chats/{chat_id}/project", headers=auth_headers, json={"project_id": project["id"]}
    )
    assert moved.status_code == 200
    assert moved.json()["data"]["project_id"] == project["id"]

    in_project = client.get(f"/api/v1/projects/{project['id']}/chats", headers=auth_headers).json()["data"]
    assert [c["id"] for c in in_project] == [chat_id]

    removed = client.patch(f"/api/v1/chats/{chat_id}/project", headers=auth_headers, json={"project_id": None})
    assert removed.json()["data"]["project_id"] is None

    ungrouped = client.get("/api/v1/chats?ungrouped_only=true", headers=auth_headers).json()["data"]
    assert chat_id in [c["id"] for c in ungrouped]


def test_deleting_a_project_detaches_chats_but_keeps_them(client, auth_headers, admin_headers, sample_pdf_bytes):
    """Deleting a folder must never destroy the conversations inside it."""
    chat_id = _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes)
    project = _create_project(client, auth_headers)
    client.patch(f"/api/v1/chats/{chat_id}/project", headers=auth_headers, json={"project_id": project["id"]})

    response = client.delete(f"/api/v1/projects/{project['id']}", headers=auth_headers)
    assert response.status_code == 200

    surviving = client.get("/api/v1/chats", headers=auth_headers).json()["data"]
    assert chat_id in [c["id"] for c in surviving], "chat must survive its project being deleted"
    assert next(c for c in surviving if c["id"] == chat_id)["project_id"] is None

    # And the conversation itself is intact.
    session = client.get(f"/api/v1/chat/sessions/{chat_id}", headers=auth_headers).json()["data"]
    assert len(session["messages"]) >= 2


def test_rename_chat(client, auth_headers, admin_headers, sample_pdf_bytes):
    chat_id = _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes)
    response = client.patch(f"/api/v1/chats/{chat_id}", headers=auth_headers, json={"title": "CAP Theorem"})
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "CAP Theorem"


def test_chat_history_excludes_admin_document_testing_sessions(
    client, admin_headers, sample_pdf_bytes
):
    """Document-scoped sessions are an admin testing artifact, not history."""
    upload = client.post(
        "/api/v1/documents/upload",
        headers=admin_headers,
        files={"files": ("sample.pdf", sample_pdf_bytes, "application/pdf")},
        data={"embedding_provider": "testembed", "embedding_model": "fake-embed-model"},
    )
    document_id = upload.json()["data"][0]["id"]
    client.post(
        "/api/v1/chat/ask",
        headers=admin_headers,
        json={"question": "test", "provider": "testchat", "model": "fake-model", "document_id": document_id},
    )

    chats = client.get("/api/v1/chats", headers=admin_headers).json()["data"]
    assert all(c["document_id"] is None for c in chats)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_matches_titles_and_message_content(client, auth_headers, admin_headers, sample_pdf_bytes):
    chat_id = _start_chat(
        client, auth_headers, admin_headers, sample_pdf_bytes, question="How many days of paid leave?"
    )
    client.patch(f"/api/v1/chats/{chat_id}", headers=auth_headers, json={"title": "Leave entitlement"})

    by_title = client.get("/api/v1/chats?search=entitlement", headers=auth_headers).json()["data"]
    assert chat_id in [c["id"] for c in by_title]

    by_content = client.get("/api/v1/chats?search=paid%20leave", headers=auth_headers).json()["data"]
    assert chat_id in [c["id"] for c in by_content]

    no_match = client.get("/api/v1/chats?search=kubernetes", headers=auth_headers).json()["data"]
    assert chat_id not in [c["id"] for c in no_match]


# ---------------------------------------------------------------------------
# Ownership - the tests that actually matter
# ---------------------------------------------------------------------------


def test_projects_are_invisible_to_other_users(client, auth_headers, other_user):
    _create_project(client, auth_headers, "Private Project")
    assert client.get("/api/v1/projects", headers=other_user).json()["data"] == []


def test_another_users_project_cannot_be_read_renamed_or_deleted(client, auth_headers, other_user):
    project = _create_project(client, auth_headers, "Mine")
    pid = project["id"]

    assert client.get(f"/api/v1/projects/{pid}/chats", headers=other_user).status_code == 404
    assert client.patch(f"/api/v1/projects/{pid}", headers=other_user, json={"name": "Hijacked"}).status_code == 404
    assert client.delete(f"/api/v1/projects/{pid}", headers=other_user).status_code == 404

    # ...and it is untouched afterwards.
    assert client.get("/api/v1/projects", headers=auth_headers).json()["data"][0]["name"] == "Mine"


def test_another_users_chat_cannot_be_renamed_or_moved(
    client, auth_headers, other_user, admin_headers, sample_pdf_bytes
):
    """Changing the id in the URL must not grant access to someone else's chat."""
    chat_id = _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes)

    assert client.patch(f"/api/v1/chats/{chat_id}", headers=other_user, json={"title": "Hijacked"}).status_code == 404
    assert (
        client.patch(f"/api/v1/chats/{chat_id}/project", headers=other_user, json={"project_id": None}).status_code
        == 404
    )


def test_a_chat_cannot_be_moved_into_another_users_project(
    client, auth_headers, other_user, admin_headers, sample_pdf_bytes
):
    """Both the chat and the destination project must belong to the caller."""
    chat_id = _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes)
    foreign_project = _create_project(client, other_user, "Theirs")

    response = client.patch(
        f"/api/v1/chats/{chat_id}/project", headers=auth_headers, json={"project_id": foreign_project["id"]}
    )
    assert response.status_code == 404


def test_search_never_returns_another_users_chats(
    client, auth_headers, other_user, admin_headers, sample_pdf_bytes
):
    _start_chat(client, auth_headers, admin_headers, sample_pdf_bytes, question="How many days of paid leave?")
    assert client.get("/api/v1/chats?search=paid%20leave", headers=other_user).json()["data"] == []


def test_project_endpoints_require_authentication(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.post("/api/v1/projects", json={"name": "x"}).status_code == 401
    assert client.get("/api/v1/chats").status_code == 401
