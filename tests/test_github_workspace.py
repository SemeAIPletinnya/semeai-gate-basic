from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from semeai_gate_basic.github_workspace import (
    GitHubWorkspaceError,
    authenticate_session,
    begin_github_authorization,
    begin_github_installation,
    consume_state,
    create_github_app_jwt,
    create_session,
    delete_benchmark_account,
    disconnect_installation,
    finish_github_authorization,
    finish_github_installation,
    get_owned_repository,
    github_configuration,
    list_benchmark_runs,
    list_repositories,
    normalize_github_identity,
    revoke_session,
    save_benchmark_run,
    sync_repositories,
    upsert_github_user,
    workspace_root,
)


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "SEMEAI_BENCHMARK_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "SEMEAI_SESSION_COOKIE_SECRET": "test-session-secret-that-is-at-least-32-bytes",
        "SEMEAI_GITHUB_CLIENT_ID": "Iv1.test-client",
        "SEMEAI_GITHUB_CLIENT_SECRET": "not-a-real-secret",
        "SEMEAI_GITHUB_CALLBACK_URL": "https://api.semeai.tech/v0/oauth/github/callback",
        "SEMEAI_GITHUB_SETUP_URL": "https://api.semeai.tech/v0/github/install/callback",
        "SEMEAI_GITHUB_APP_ID": "12345",
        "SEMEAI_GITHUB_APP_SLUG": "semeai-repository-workspace-test",
        "SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech",
    }


def _profile(user_id: int = 4242, login: str = "octo-user") -> dict[str, object]:
    return {
        "id": user_id,
        "login": login,
        "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}?v=4",
        "name": "Octo User",
        "email": "must-not-be-used@example.com",
    }


def test_configuration_only_reports_complete_operator_dependencies(tmp_path: Path) -> None:
    env = _env(tmp_path)
    configuration = github_configuration(env=env)
    assert configuration["enabled"] is True
    assert configuration["app_configured"] is False

    private_key = tmp_path / "github-app.pem"
    private_key.write_text("test-only-placeholder", encoding="utf-8")
    env["SEMEAI_GITHUB_PRIVATE_KEY_PATH"] = str(private_key)
    configuration = github_configuration(env=env)
    assert configuration["enabled"] is True
    assert configuration["app_configured"] is True

    env.pop("SEMEAI_SESSION_COOKIE_SECRET")
    assert github_configuration(env=env)["enabled"] is False


def _auth(tmp_path: Path) -> tuple[dict[str, str], dict[str, object], str]:
    env = _env(tmp_path)
    user = upsert_github_user(_profile(), env=env)
    session = create_session(str(user["user_id"]), env=env)
    auth = authenticate_session(session["session_token"], env=env)
    return env, auth, session["session_token"]


def test_state_is_random_bound_expiring_and_one_time(tmp_path: Path) -> None:
    env = _env(tmp_path)
    started = begin_github_authorization(env=env)
    stored_states = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (workspace_root(env=env) / "states").glob("*.json")
    )
    assert started["state"] not in stored_states

    with pytest.raises(GitHubWorkspaceError) as wrong_browser:
        consume_state(started["state"], kind="authorization", binding_hash="wrong", env=env)
    assert wrong_browser.value.code == "invalid_state"

    from semeai_gate_basic.github_workspace import _digest

    binding = _digest(started["browser_token"], purpose="oauth-browser", env=env)
    consumed = consume_state(started["state"], kind="authorization", binding_hash=binding, env=env)
    assert consumed["used_at"]
    with pytest.raises(GitHubWorkspaceError) as reused:
        consume_state(started["state"], kind="authorization", binding_hash=binding, env=env)
    assert reused.value.code == "reused_state"

    expired = begin_github_authorization(env=env)
    state_file = workspace_root(env=env) / "states" / f"{_digest(expired['state'], purpose='github-state', env=env)}.json"
    record = json.loads(state_file.read_text(encoding="utf-8"))
    record["expires_at"] = "2000-01-01T00:00:00Z"
    state_file.write_text(json.dumps(record), encoding="utf-8")
    expired_binding = _digest(expired["browser_token"], purpose="oauth-browser", env=env)
    with pytest.raises(GitHubWorkspaceError) as expired_error:
        consume_state(expired["state"], kind="authorization", binding_hash=expired_binding, env=env)
    assert expired_error.value.code == "expired_state"


def test_callback_normalizes_numeric_identity_and_discards_access_token(tmp_path: Path) -> None:
    env = _env(tmp_path)
    started = begin_github_authorization(env=env)
    calls: list[dict[str, object] | None] = []

    def requester(url, method, headers, body):
        calls.append(body)
        if url.endswith("access_token"):
            return {"access_token": "ghu_ephemeral-should-not-be-stored"}
        assert headers["Authorization"].endswith("ghu_ephemeral-should-not-be-stored")
        return _profile()

    result = finish_github_authorization(
        code="temporary-code",
        state=started["state"],
        browser_token=started["browser_token"],
        env=env,
        request_json=requester,
    )
    assert result["user"]["github_user_id"] == 4242
    assert result["user"]["github_login"] == "octo-user"
    assert "email" not in result["user"]
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in workspace_root(env=env).rglob("*.json"))
    assert "temporary-code" not in serialized
    assert "ghu_ephemeral-should-not-be-stored" not in serialized
    assert env["SEMEAI_GITHUB_CLIENT_SECRET"] not in serialized


def test_callback_rejects_denial_missing_code_and_exchange_failure(tmp_path: Path) -> None:
    env = _env(tmp_path)
    started = begin_github_authorization(env=env)
    with pytest.raises(GitHubWorkspaceError) as denied:
        finish_github_authorization(
            code="", state=started["state"], browser_token=started["browser_token"], env=env
        )
    assert denied.value.code == "authorization_denied"

    started = begin_github_authorization(env=env)
    with pytest.raises(GitHubWorkspaceError) as exchange:
        finish_github_authorization(
            code="code",
            state=started["state"],
            browser_token=started["browser_token"],
            env=env,
            request_json=lambda *_: {},
        )
    assert exchange.value.code == "github_exchange_failed"


def test_session_expiration_and_logout(tmp_path: Path) -> None:
    env, auth, raw = _auth(tmp_path)
    assert auth["user"]["github_user_id"] == 4242
    assert revoke_session(raw, env=env)["status"] == "logged_out"
    with pytest.raises(GitHubWorkspaceError):
        authenticate_session(raw, env=env)

    user = upsert_github_user(_profile(5000, "later-user"), env=env)
    session = create_session(str(user["user_id"]), env=env)
    with pytest.raises(GitHubWorkspaceError) as expired:
        authenticate_session(
            session["session_token"], env=env, now=datetime.now(timezone.utc) + timedelta(days=8)
        )
    assert expired.value.code == "session_expired"


def test_installation_ownership_repository_boundary_and_private_isolation(tmp_path: Path, monkeypatch) -> None:
    env, auth, _ = _auth(tmp_path)
    monkeypatch.setattr("semeai_gate_basic.github_workspace._app_headers", lambda _env: {"Authorization": "Bearer test-jwt"})
    started = begin_github_installation(auth, env=env)

    def install_requester(url, method, headers, body):
        assert url.endswith("/777")
        return {"id": 777, "account": {"id": 4242, "login": "octo-user"}, "suspended_at": None}

    installation = finish_github_installation(
        installation_id="777",
        state=started["state"],
        auth=auth,
        env=env,
        request_json=install_requester,
    )
    assert installation["user_id"] == auth["user"]["user_id"]

    def repository_requester(url, method, headers, body):
        if url.endswith("access_tokens"):
            assert body == {"permissions": {"contents": "read", "metadata": "read"}}
            return {"token": "ghs_ephemeral-installation"}
        return {
            "total_count": 1,
            "repositories": [
                {
                    "id": 9001,
                    "full_name": "octo-user/private-evidence",
                    "private": True,
                    "default_branch": "main",
                    "owner": {"login": "octo-user"},
                }
            ],
        }

    repositories = sync_repositories(auth, 777, env=env, request_json=repository_requester)
    assert repositories[0]["private"] is True
    assert get_owned_repository(auth, 9001, env=env)["full_name"] == "octo-user/private-evidence"
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in workspace_root(env=env).rglob("*.json"))
    assert "ghs_ephemeral-installation" not in serialized

    other_user = upsert_github_user(_profile(9999, "other-user"), env=env)
    other_session = create_session(str(other_user["user_id"]), env=env)
    other_auth = authenticate_session(other_session["session_token"], env=env)
    with pytest.raises(GitHubWorkspaceError):
        get_owned_repository(other_auth, 9001, env=env)

    disconnected = disconnect_installation(auth, 777, env=env)
    assert disconnected["history_preserved"] is True
    assert list_repositories(auth, env=env)[0]["connection_status"] == "disconnected"


def test_installation_cannot_be_reassigned_and_removed_selection_is_disconnected(
    tmp_path: Path, monkeypatch
) -> None:
    env, auth, _ = _auth(tmp_path)
    monkeypatch.setattr("semeai_gate_basic.github_workspace._app_headers", lambda _env: {})
    started = begin_github_installation(auth, env=env)
    finish_github_installation(
        installation_id="818",
        state=started["state"],
        auth=auth,
        env=env,
        request_json=lambda *_: {
            "id": 818,
            "account": {"id": 4242, "login": "octo-user"},
            "suspended_at": None,
        },
    )

    responses = [
        {
            "total_count": 1,
            "repositories": [
                {
                    "id": 9100,
                    "full_name": "octo-user/selected-once",
                    "private": True,
                    "default_branch": "main",
                    "owner": {"login": "octo-user"},
                }
            ],
        },
        {"total_count": 0, "repositories": []},
    ]

    def requester(url, method, headers, body):
        if url.endswith("access_tokens"):
            return {"token": "temporary"}
        return responses.pop(0)

    sync_repositories(auth, 818, env=env, request_json=requester)
    sync_repositories(auth, 818, env=env, request_json=requester)
    assert list_repositories(auth, env=env)[0]["connection_status"] == "disconnected"
    with pytest.raises(GitHubWorkspaceError):
        get_owned_repository(auth, 9100, env=env)

    other_user = upsert_github_user(_profile(1919, "second-user"), env=env)
    other_session = create_session(str(other_user["user_id"]), env=env)
    other_auth = authenticate_session(other_session["session_token"], env=env)
    other_state = begin_github_installation(other_auth, env=env)
    with pytest.raises(GitHubWorkspaceError) as conflict:
        finish_github_installation(
            installation_id="818",
            state=other_state["state"],
            auth=other_auth,
            env=env,
            request_json=lambda *_: {
                "id": 818,
                "account": {"id": 1919, "login": "second-user"},
                "suspended_at": None,
            },
        )
    assert conflict.value.status_code == 409


def test_account_deletion_removes_identity_sessions_history_and_keeps_no_cross_user_data(tmp_path: Path) -> None:
    env, auth, _ = _auth(tmp_path)
    root = workspace_root(env=env)
    other = upsert_github_user(_profile(6000, "retained-user"), env=env)
    create_session(str(other["user_id"]), env=env)
    (root / "runs" / "run_aaaaaaaaaaaaaaaaaaaaaaaa.json").write_text(
        json.dumps({"user_id": auth["user"]["user_id"]}), encoding="utf-8"
    )
    deleted = delete_benchmark_account(auth, env=env)
    assert deleted["deleted"]["users"] == 1
    assert not (root / "users" / f"{auth['user']['user_id']}.json").exists()
    assert (root / "users" / f"{other['user_id']}.json").exists()
    assert list_benchmark_runs({"user": other}, env=env) == []


def test_invalid_github_identity_never_falls_back_to_login_or_email() -> None:
    with pytest.raises(GitHubWorkspaceError):
        normalize_github_identity({"login": "octocat", "email": "octo@example.com"})
    with pytest.raises(GitHubWorkspaceError):
        normalize_github_identity({"id": "not-numeric", "login": "octocat"})


def test_github_app_jwt_is_short_lived_and_rs256_signed(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "github-app-private-key.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    env = _env(tmp_path)
    env["SEMEAI_GITHUB_PRIVATE_KEY_PATH"] = str(key_path)
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    token = create_github_app_jwt(env=env, now=now)
    encoded_header, encoded_payload, encoded_signature = token.split(".")

    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    header = json.loads(decode(encoded_header))
    payload = json.loads(decode(encoded_payload))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload == {
        "iat": int(now.timestamp()) - 30,
        "exp": int(now.timestamp()) + 540,
        "iss": "12345",
    }
    private_key.public_key().verify(
        decode(encoded_signature),
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
