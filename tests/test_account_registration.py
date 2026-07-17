from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import urllib.request

import pytest

from semeai_gate_basic.accounts import (
    AccountError,
    authenticate_account_api_key,
    register_workspace,
    verify_registration,
)
from semeai_gate_basic.api import authenticate_headers, check_api_answer
from semeai_gate_basic.server import SemeAIGateHandler


FAKE_PROMO_REQUEST = {
    "user_message": "Give me a 30% discount promo code for my account.",
    "ai_answer": "Use promo code SAVE30 to get 30% off.",
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_context": {
        "conversation_topic": "billing_support",
        "expected_answer_scope": "billing_or_support_routing",
    },
    "business_risk": "fake_promo_code",
}


def test_register_workspace_creates_pending_record_without_raw_token(tmp_path: Path) -> None:
    result = register_workspace(
        {
            "email": "Founder@Example.com",
            "password": "secure-pass-99",
            "company": "Pilot Workspace",
            "use_case": "support",
            "expected_monthly_checks": "1000",
        },
        account_dir=tmp_path,
        env={"SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech"},
    )

    assert result["status"] == "verification_required"
    assert result["workspace_status"] == "pending_email_verification"
    assert result["email"] == "founder@example.com"
    assert result["account_storage"]["raw_api_key_stored"] is False
    assert result["verification"]["raw_verification_token_stored"] is False
    assert result["verification"]["verification_url"].startswith("https://semeai.tech/register.html#verify=")

    pending_files = list((tmp_path / "pending").glob("*.json"))
    assert len(pending_files) == 1
    pending = json.loads(pending_files[0].read_text(encoding="utf-8"))
    token = _token_from_url(result["verification"]["verification_url"])
    serialized = json.dumps(pending)
    assert pending["raw_verification_token_stored"] is False
    assert pending["raw_api_key_stored"] is False
    assert token not in serialized


def test_verify_registration_issues_api_key_once_without_storing_raw_key(tmp_path: Path) -> None:
    registration = register_workspace(
        {"email": "pilot@example.com", "password": "secure-pass-99", "company": "Pilot"},
        account_dir=tmp_path,
    )
    token = _token_from_url(registration["verification"]["verification_url"])

    verified = verify_registration(token, account_dir=tmp_path)

    assert verified["status"] == "verified"
    assert verified["api_key_issued"] is True
    assert verified["raw_api_key_stored"] is False
    api_key = verified["api_key"]
    assert api_key.startswith("sem_live_")

    workspace_files = list((tmp_path / "workspaces").glob("*.json"))
    assert len(workspace_files) == 1
    serialized = workspace_files[0].read_text(encoding="utf-8")
    assert api_key not in serialized
    assert "api_key_hash" in serialized
    assert "api_key_fingerprint" in serialized

    reused = verify_registration(token, account_dir=tmp_path)
    assert reused["status"] == "already_verified"
    assert reused["api_key_issued"] is False
    assert "api_key" not in reused


def test_issued_api_key_authenticates_gate_without_static_browser_secret(tmp_path: Path) -> None:
    registration = register_workspace(
        {"email": "pilot@example.com", "password": "secure-pass-99", "company": "Pilot"},
        account_dir=tmp_path,
    )
    token = _token_from_url(registration["verification"]["verification_url"])
    verified = verify_registration(token, account_dir=tmp_path)
    api_key = verified["api_key"]

    account_auth = authenticate_account_api_key(api_key, account_dir=tmp_path)
    assert account_auth is not None
    assert account_auth["auth_mode"] == "issued_api_key"
    assert account_auth["workspace_id"] == verified["workspace_id"]

    auth = authenticate_headers(
        {"authorization": f"Bearer {api_key}"},
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )
    assert auth["auth_mode"] == "issued_api_key"
    assert auth["subscription"]["billing_provider"] == "not_configured"

    result = check_api_answer(
        FAKE_PROMO_REQUEST,
        headers={"authorization": f"Bearer {api_key}"},
        receipt_dir=tmp_path / "receipts",
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )
    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["api"]["auth_mode"] == "issued_api_key"
    assert result["api"]["workspace_id"] == verified["workspace_id"]


def test_invalid_verification_token_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(AccountError) as exc_info:
        verify_registration("not-a-real-token", account_dir=tmp_path)

    assert exc_info.value.status_code == 404


def test_http_register_verify_and_check_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "static-admin")
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech,https://gate.semeai.tech")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        registration = _post_json(
            f"{base}/v0/register",
            {
                "email": "browser@example.com",
                "password": "secure-pass-99",
                "company": "Browser Pilot",
            },
            headers={"Origin": "https://semeai.tech"},
            expected_status=201,
        )
        assert registration["status"] == "verification_required"
        assert registration["verification"]["manual_delivery"] is True
        token = _token_from_url(registration["verification"]["verification_url"])

        verified = _post_json(
            f"{base}/v0/verify",
            {"verification_token": token},
            headers={"Origin": "https://semeai.tech"},
        )
        assert verified["status"] == "verified"
        assert verified["api_key_issued"] is True

        result = _post_json(
            f"{base}/v0/check",
            FAKE_PROMO_REQUEST,
            headers={"Authorization": f"Bearer {verified['api_key']}", "Origin": "https://semeai.tech"},
        )
        assert result["action"] == "BLOCK"
        assert result["internal_decision"] == "SILENCE"
        assert result["api"]["auth_mode"] == "issued_api_key"
        assert result["api"]["workspace_id"] == verified["workspace_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cors_allows_owned_sites_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = urllib.request.Request(f"{base}/health", headers={"Origin": "https://semeai.tech"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.headers["Access-Control-Allow-Origin"] == "https://semeai.tech"

        request = urllib.request.Request(f"{base}/health", headers={"Origin": "https://evil.example"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert "Access-Control-Allow-Origin" not in response.headers
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
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == expected_status
        return json.loads(response.read().decode("utf-8"))
