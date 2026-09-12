"""Hardening headers on API responses.

The headers matter most on responses nobody writes by hand - errors,
rejections, 404s - which is why several of these deliberately assert against
failure responses rather than happy paths.
"""
import pytest

from app.core.config import get_settings

EXPECTED = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@pytest.mark.parametrize("header,value", sorted(EXPECTED.items()))
def test_security_headers_present(client, header, value):
    response = client.get("/health")
    assert response.headers.get(header) == value


def test_api_denies_every_content_source_by_default(client):
    """The API serves JSON, so it should never be permitted to load anything."""
    csp = client.get("/health").headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_headers_are_applied_to_error_responses(client, auth_headers):
    """An error path must not be a gap in the hardening."""
    response = client.get("/api/v1/chat/sessions/does-not-exist", headers=auth_headers)
    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]


def test_headers_are_applied_to_unauthenticated_rejections(client):
    response = client.get("/api/v1/documents")
    assert response.status_code == 401
    assert response.headers["X-Frame-Options"] == "DENY"


def test_headers_are_applied_when_the_body_is_rejected_as_too_large(client, auth_headers):
    """MaxBodySizeMiddleware short-circuits before routing; the security
    middleware is registered outermost precisely so this still gets them."""
    settings = get_settings()
    oversized = str(settings.max_request_body_mb * 1024 * 1024 + 1)
    response = client.post(
        "/api/v1/chat/ask",
        headers={**auth_headers, "content-length": oversized},
        json={"question": "x", "provider": "testchat", "model": "fake-model"},
    )
    assert response.status_code == 413
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_docs_get_a_policy_that_lets_them_actually_render(client):
    """A blanket 'load nothing' policy would leave Swagger UI blank, so the
    docs paths get their own policy - still without framing or a base tag."""
    response = client.get("/docs")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'none'" in csp
    # The relaxation must not leak onto the API itself.
    assert "cdn.jsdelivr.net" not in client.get("/health").headers["Content-Security-Policy"]


def test_hsts_is_not_sent_over_plain_http(client):
    """Asserting HSTS from a dev server would pin a hostname to HTTPS before
    a certificate exists for it."""
    assert "Strict-Transport-Security" not in client.get("/health").headers


def test_hsts_is_sent_when_a_proxy_reports_https(client):
    response = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    assert "includeSubDomains" in response.headers["Strict-Transport-Security"]


def test_application_sets_a_neutral_server_header(client):
    assert client.get("/health").headers.get("Server") == get_settings().app_name


def test_launch_commands_suppress_uvicorn_s_own_server_banner():
    """The application header alone is not enough.

    uvicorn appends `server: uvicorn` after the app has responded, so
    middleware cannot replace it and TestClient never shows it - a real
    server emits both headers. Suppressing it is therefore a launch flag,
    and that flag is what this test pins.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    launchers = {
        "backend/docker-entrypoint.sh": root / "backend" / "docker-entrypoint.sh",
        "run_backend.bat": root / "run_backend.bat",
    }

    for name, path in launchers.items():
        if not path.exists():
            continue
        commands = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            # An invocation, not the comment above it explaining the flag.
            if "uvicorn " in line and ":app" in line and not line.strip().startswith(("#", "REM", "::"))
        ]
        assert commands, f"found no uvicorn invocation in {name} - has it been renamed?"
        for command in commands:
            assert "--no-server-header" in command, (
                f"{name} starts uvicorn without --no-server-header, so it will "
                f"advertise the stack: {command}"
            )


def test_headers_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "security_headers_enabled", False)
    assert "Content-Security-Policy" not in client.get("/health").headers


def test_no_endpoint_authenticates_from_a_cookie():
    """Guards the reasoning behind having no CSRF tokens.

    Bearer-token auth carries no ambient credentials, so CSRF tokens would
    add nothing. If an endpoint ever starts reading auth from a cookie, that
    argument collapses - this test is what makes the change visible.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if "set_cookie" in path.read_text(encoding="utf-8")
        or "request.cookies" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"cookie-based auth appeared in {offenders}; revisit CSRF protection"
