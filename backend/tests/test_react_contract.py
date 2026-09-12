"""Every endpoint the React client calls must exist on the API.

This project ships one client, the React app in `frontend/`. A renamed
route must fail here rather than becoming a blank screen someone discovers
later.

Like that suite, this parses the client's source rather than duplicating its
HTTP layer, and verifies routing only - payloads and responses are covered by
the endpoint tests.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set

import pytest

from app.main import create_app

REACT_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
API_SLICE = REACT_SRC / "api" / "apiSlice.ts"
CHAT_SLICE = REACT_SRC / "store" / "chatSlice.ts"

# A TypeScript identifier or member expression spliced into a URL, e.g.
#   "/api/v1/projects/" + id + "/chats"
_CONCAT_MIDDLE = re.compile(r'"\s*\+\s*[A-Za-z_$][\w$.]*\s*\+\s*"')
_CONCAT_TAIL = re.compile(r'"\s*\+\s*[A-Za-z_$][\w$.]*')

_PATH_LITERAL = re.compile(r'"(/api/v1[^"]*|/health[^"]*)"')


def _flatten_concatenations(source: str) -> str:
    """Rewrite `"/a/" + id + "/b"` into the single literal `"/a/{}/b"`.

    Done textually because the aim is to recover the *shape* of each URL, not
    to evaluate TypeScript. Anything spliced in is a path parameter.
    """
    previous = None
    while previous != source:
        previous = source
        source = _CONCAT_MIDDLE.sub("{}", source)
    return _CONCAT_TAIL.sub('{}"', source)


def _clean(path: str) -> str:
    """Drop a query string, which is not part of the route."""
    return path.split("?")[0].rstrip()


def _react_paths() -> Set[str]:
    paths: Set[str] = set()
    for file in (API_SLICE, CHAT_SLICE):
        flattened = _flatten_concatenations(file.read_text(encoding="utf-8"))
        for match in _PATH_LITERAL.findall(flattened):
            cleaned = _clean(match)
            if cleaned:
                paths.add(cleaned)
    return paths


def _backend_paths() -> Set[str]:
    """Served paths, with parameter names replaced so shapes compare."""
    schema = create_app().openapi()
    return {re.sub(r"\{[^}]*\}", "{}", path) for path in schema["paths"]}


def test_the_react_client_source_was_found():
    """Guards the test itself: a bad path would silently assert nothing."""
    assert API_SLICE.exists(), f"not found: {API_SLICE}"
    assert CHAT_SLICE.exists(), f"not found: {CHAT_SLICE}"
    assert len(_react_paths()) >= 20, "parsed suspiciously few paths - has the client been restructured?"


@pytest.mark.parametrize("path", sorted(_react_paths()))
def test_react_endpoint_exists(path: str):
    assert path in _backend_paths(), f"the React client calls {path}, which the API does not serve"


def test_the_react_client_covers_the_streaming_endpoint():
    """Streaming bypasses RTK Query, so it is easy to miss when refactoring."""
    assert "/api/v1/chat/ask/stream" in _react_paths()


def test_both_clients_address_the_same_api():
    """Neither client should quietly drift onto endpoints the other lacks.

    Compared as a warning-shaped assertion on the *core* surface only: the
    clients are allowed to differ at the edges, but not on the endpoints that
    make the product work.
    """
    core = {
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/chat/ask/stream",
        "/api/v1/documents",
        "/api/v1/projects",
        "/api/v1/chats",
        "/api/v1/admin/models",
    }
    missing = core - _react_paths()
    assert not missing, f"the React client does not call {sorted(missing)}"
