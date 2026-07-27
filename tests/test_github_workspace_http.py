from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from semeai_gate_basic.github_workspace import create_session, upsert_github_user
from semeai_gate_basic.github_workspace import GitHubWorkspaceError, authenticate_session
from semeai_gate_basic.server import SemeAIGateHandler


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEMEAI_BENCHMARK_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("SEMEAI_SESSION_COOKIE_SECRET", "http-test-session-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("SEMEAI_GITHUB_CLIENT_ID", "Iv1.http-test")
    monkeypatch.setenv("SEMEAI_GITHUB_CLIENT_SECRET", "not-a-real-client-secret")
    monkeypatch.setenv("SEMEAI_GITHUB_CALLBACK_URL", "https://api.semeai.tech/v0/oauth/github/callback")
    monkeypatch.setenv("SEMEAI_GITHUB_SETUP_URL", "https://api.semeai.tech/v0/github/install/callback")
    monkeypatch.setenv("SEMEAI_GITHUB_APP_ID", "12345")
    monkeypatch.setenv("SEMEAI_GITHUB_APP_SLUG", "semeai-repository-workspace-test")
    monkeypatch.setenv("SEMEAI_GATE_PUBLIC_SITE_URL", "https://semeai.tech")
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech")


def _request_no_redirect(url: str, *, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        return urllib.request.build_opener(_NoRedirect()).open(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc


def _post(
    url: str,
    payload: bytes,
    *,
    cookie: str,
    origin: str,
):
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Origin": origin,
        },
    )
    try:
        return urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc


@pytest.fixture
def workspace_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _configure(monkeypatch, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_oauth_start_cookie_state_binding_and_denial_redirect(workspace_server: str) -> None:
    start = _request_no_redirect(f"{workspace_server}/v0/oauth/github/start?return_path=%2Fbenchmark%2Fworkspace%2F")
    assert start.code == 302
    location = start.headers["Location"]
    parsed = urllib.parse.urlparse(location)
    assert parsed.scheme == "https" and parsed.hostname == "github.com"
    state = urllib.parse.parse_qs(parsed.query)["state"][0]
    binding_cookie = start.headers.get_all("Set-Cookie")[0]
    assert state not in binding_cookie
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/v0", "Max-Age=600"):
        assert attribute in binding_cookie

    denied = _request_no_redirect(
        f"{workspace_server}/v0/oauth/github/callback?error=access_denied&state={urllib.parse.quote(state)}",
        headers={"Cookie": binding_cookie.split(";", 1)[0]},
    )
    assert denied.code == 302
    assert denied.headers["Location"] == "https://semeai.tech/benchmark/workspace/?auth=denied"
    assert "Max-Age=0" in denied.headers.get_all("Set-Cookie")[0]


def test_authenticated_me_exact_credentialed_cors_logout_and_malformed_json(
    workspace_server: str, tmp_path: Path
) -> None:
    env = {
        "SEMEAI_BENCHMARK_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "SEMEAI_SESSION_COOKIE_SECRET": "http-test-session-secret-that-is-at-least-32-bytes",
    }
    user = upsert_github_user(
        {
            "id": 8080,
            "login": "workspace-user",
            "avatar_url": "https://avatars.githubusercontent.com/u/8080?v=4",
            "name": "Workspace User",
        },
        env=env,
    )
    session = create_session(user["user_id"], env=env)
    cookie = f"semeai_benchmark_session={session['session_token']}"

    me = urllib.request.urlopen(
        urllib.request.Request(
            f"{workspace_server}/v0/me",
            headers={"Cookie": cookie, "Origin": "https://semeai.tech"},
        ),
        timeout=10,
    )
    payload = json.loads(me.read())
    assert payload["authenticated"] is True
    assert payload["user"]["github_user_id"] == 8080
    assert me.headers["Access-Control-Allow-Origin"] == "https://semeai.tech"
    assert me.headers["Access-Control-Allow-Credentials"] == "true"
    assert me.headers["Cache-Control"] == "no-store, private"

    malformed = _post(
        f"{workspace_server}/v0/benchmark/runs",
        b"{not-json",
        cookie=cookie,
        origin="https://semeai.tech",
    )
    assert malformed.code == 400

    rejected = _post(
        f"{workspace_server}/v0/oauth/github/logout",
        b"{}",
        cookie=cookie,
        origin="https://evil.example",
    )
    assert rejected.code == 403
    assert rejected.headers.get("Access-Control-Allow-Origin") is None

    logout = _post(
        f"{workspace_server}/v0/oauth/github/logout",
        b"{}",
        cookie=cookie,
        origin="https://semeai.tech",
    )
    assert logout.code == 200
    assert "HttpOnly" in logout.headers.get_all("Set-Cookie")[0]
    assert "Secure" in logout.headers.get_all("Set-Cookie")[0]
    assert "SameSite=Lax" in logout.headers.get_all("Set-Cookie")[0]
    assert "Max-Age=0" in logout.headers.get_all("Set-Cookie")[0]

    expired = _request_no_redirect(f"{workspace_server}/v0/me", headers={"Cookie": cookie})
    assert expired.code == 401


def test_repository_get_is_read_only_and_refresh_requires_post_origin(
    workspace_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {
        "SEMEAI_BENCHMARK_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "SEMEAI_SESSION_COOKIE_SECRET": "http-test-session-secret-that-is-at-least-32-bytes",
    }
    user = upsert_github_user(
        {
            "id": 8181,
            "login": "read-only-list",
            "avatar_url": "https://avatars.githubusercontent.com/u/8181?v=4",
            "name": "Read Only",
        },
        env=env,
    )
    session = create_session(user["user_id"], env=env)
    cookie = f"semeai_benchmark_session={session['session_token']}"

    def fail_sync(*_args, **_kwargs):
        raise AssertionError("GET repository listing must not synchronize")

    monkeypatch.setattr("semeai_gate_basic.github_workspace_http.sync_repositories", fail_sync)
    listing = _request_no_redirect(
        f"{workspace_server}/v0/github/repositories?refresh=1",
        headers={"Cookie": cookie, "Origin": "https://semeai.tech"},
    )
    assert listing.code == 200
    assert json.loads(listing.read()) == {"repositories": []}

    rejected = _post(
        f"{workspace_server}/v0/github/repositories/refresh",
        b"{}",
        cookie=cookie,
        origin="https://evil.example",
    )
    assert rejected.code == 403

    refreshed = _post(
        f"{workspace_server}/v0/github/repositories/refresh",
        b"{}",
        cookie=cookie,
        origin="https://semeai.tech",
    )
    assert refreshed.code == 200
    assert json.loads(refreshed.read()) == {"repositories": []}


def test_oauth_start_rejects_open_redirect(workspace_server: str) -> None:
    response = _request_no_redirect(
        f"{workspace_server}/v0/oauth/github/start?return_path=https%3A%2F%2Fevil.example%2F"
    )
    assert response.code == 400
    assert json.loads(response.read())["code"] == "invalid_return_path"


def test_successful_callback_rotates_and_revokes_existing_session(
    workspace_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {
        "SEMEAI_BENCHMARK_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "SEMEAI_SESSION_COOKIE_SECRET": "http-test-session-secret-that-is-at-least-32-bytes",
    }
    user = upsert_github_user(
        {
            "id": 9090,
            "login": "rotation-user",
            "avatar_url": "https://avatars.githubusercontent.com/u/9090?v=4",
            "name": "Rotation User",
        },
        env=env,
    )
    old_session = create_session(user["user_id"], env=env)
    new_session = create_session(user["user_id"], env=env)
    monkeypatch.setattr(
        "semeai_gate_basic.github_workspace_http.finish_github_authorization",
        lambda **_: {
            "user": user,
            "session": new_session,
            "return_path": "/benchmark/workspace/",
        },
    )
    callback = _request_no_redirect(
        f"{workspace_server}/v0/oauth/github/callback?code=temporary&state=bound",
        headers={
            "Cookie": (
                f"semeai_benchmark_session={old_session['session_token']}; "
                "semeai_benchmark_oauth=browser-binding"
            )
        },
    )
    assert callback.code == 302
    assert callback.headers["Location"] == "https://semeai.tech/benchmark/workspace/"
    assert "temporary" not in callback.headers["Location"]
    assert "bound" not in callback.headers["Location"]
    session_cookie = next(
        value
        for value in callback.headers.get_all("Set-Cookie")
        if value.startswith("semeai_benchmark_session=")
    )
    assert new_session["session_token"] in session_cookie
    with pytest.raises(GitHubWorkspaceError):
        authenticate_session(old_session["session_token"], env=env)
    assert authenticate_session(new_session["session_token"], env=env)["user"]["github_user_id"] == 9090


def test_callback_query_secrets_are_redacted_from_access_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SEMEAI_GATE_ACCESS_LOG", "true")
    handler = object.__new__(SemeAIGateHandler)
    handler.client_address = ("127.0.0.1", 12345)
    handler.log_message(
        '"%s" %s %s',
        "GET /v0/oauth/github/callback?code=secret-code&state=secret-state HTTP/1.1",
        "400",
        "-",
    )
    handler.log_message(
        '"%s" %s %s',
        "GET /v0/github/install/callback?installation_id=777&state=install-secret HTTP/1.1",
        "400",
        "-",
    )
    logged = capsys.readouterr().err
    assert "[redacted]" in logged
    assert "secret-code" not in logged
    assert "secret-state" not in logged
    assert "install-secret" not in logged
