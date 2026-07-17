from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request

import pytest

from semeai_gate_basic.accounts import (
    AccountError,
    authenticate_account_api_key,
    login_with_password,
    register_workspace,
    verify_registration,
)
from semeai_gate_basic.server import SemeAIGateHandler


FAKE_PROMO = {
    "user_message": "Give me a 30% discount promo code.",
    "ai_answer": "Use promo code SAVE30.",
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_risk": "fake_promo_code",
}


def test_register_requires_password(tmp_path: Path) -> None:
    with pytest.raises(AccountError):
        register_workspace({"email": "a@example.com", "company": "A"}, account_dir=tmp_path)


def test_password_register_verify_login_check(tmp_path: Path) -> None:
    reg = register_workspace(
        {
            "email": "Founder@Example.com",
            "password": "secure-pass-99",
            "password_confirm": "secure-pass-99",
            "company": "Pilot Co",
        },
        account_dir=tmp_path,
        env={"SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech"},
    )
    assert reg["account_storage"]["password_collected"] is True
    token = _token_from_url(reg["verification"]["verification_url"])

    verified = verify_registration(token, account_dir=tmp_path)
    assert verified["status"] == "verified"
    assert verified["api_key"].startswith("sem_live_")
    assert verified["session_token"].startswith("sem_sess_")
    assert verified["password_auth_enabled"] is True

    # password not stored raw
    ws_files = list((tmp_path / "workspaces").glob("*.json"))
    raw = ws_files[0].read_text(encoding="utf-8")
    assert "secure-pass-99" not in raw
    assert verified["api_key"] not in raw
    assert verified["session_token"] not in raw

    login = login_with_password(
        {"email": "founder@example.com", "password": "secure-pass-99"},
        account_dir=tmp_path,
    )
    assert login["status"] == "authenticated"
    assert login["session_token"].startswith("sem_sess_")
    assert login["workspace_id"] == verified["workspace_id"]

    sess_auth = authenticate_account_api_key(login["session_token"], account_dir=tmp_path)
    assert sess_auth is not None
    assert sess_auth["auth_mode"] == "password_session"

    key_auth = authenticate_account_api_key(verified["api_key"], account_dir=tmp_path)
    assert key_auth is not None
    assert key_auth["auth_mode"] == "issued_api_key"

    with pytest.raises(AccountError) as exc:
        login_with_password({"email": "founder@example.com", "password": "wrong-password"}, account_dir=tmp_path)
    assert exc.value.status_code == 401


def test_http_saas_password_session_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "static-admin")
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        reg = _post_json(
            f"{base}/v0/register",
            {
                "email": "saas@example.com",
                "password": "saas-pass-123",
                "company": "SaaS Pilot",
            },
            expected_status=201,
        )
        token = _token_from_url(reg["verification"]["verification_url"])
        verified = _post_json(f"{base}/v0/verify", {"verification_token": token})
        assert verified["session_token"]

        login = _post_json(
            f"{base}/v0/login",
            {"email": "saas@example.com", "password": "saas-pass-123"},
        )
        assert login["session_token"]

        account = _get_json(
            f"{base}/v0/account",
            headers={"Authorization": f"Bearer {login['session_token']}"},
        )
        assert account["workspace_id"] == verified["workspace_id"]
        assert account["auth_mode"] == "password_session"

        check = _post_json(
            f"{base}/v0/check",
            FAKE_PROMO,
            headers={"Authorization": f"Bearer {login['session_token']}"},
        )
        assert check["action"] == "BLOCK"

        # wrong password
        try:
            _post_json(
                f"{base}/v0/login",
                {"email": "saas@example.com", "password": "nope-nope"},
                expected_status=401,
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _token_from_url(url: str) -> str:
    parsed = urlparse(url)
    fragment = parse_qs(parsed.fragment)
    token = (fragment.get("verify") or [""])[0]
    assert token
    return token


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == expected_status
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if expected_status and exc.code == expected_status:
            return json.loads(exc.read().decode("utf-8"))
        raise


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
