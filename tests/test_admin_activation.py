from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from semeai_gate_basic.accounts import register_workspace, verify_registration
from semeai_gate_basic.admin import (
    AdminAuthError,
    activate_workspace_after_manual_review,
    authenticate_admin_headers,
    list_billing_reviews,
)
from semeai_gate_basic.api import authenticate_headers, check_api_answer
from semeai_gate_basic.billing import create_manual_crypto_intent, submit_manual_crypto_txid
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

TXID = "a" * 64


def test_admin_auth_requires_configured_key() -> None:
    try:
        authenticate_admin_headers({"authorization": "Bearer anything"}, env={})
    except AdminAuthError as exc:
        assert exc.status_code == 503
    else:  # pragma: no cover - defensive clarity
        raise AssertionError("admin auth should fail closed without SEMEAI_GATE_ADMIN_KEY")


def test_manual_crypto_review_activation_is_admin_only_and_not_gate_authority(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)
    auth = authenticate_headers(
        {"authorization": f"Bearer {verified['api_key']}"},
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )
    intent = create_manual_crypto_intent(auth, {"amount_usdt": "25.00", "plan": "pilot"}, account_dir=tmp_path)
    invoice_id = intent["invoice"]["invoice_id"]

    proof = submit_manual_crypto_txid(auth, {"invoice_id": invoice_id, "txid": TXID}, account_dir=tmp_path)
    assert proof["status"] == "pending_review"
    assert proof["manual_review_required"] is True

    reviews = list_billing_reviews(account_dir=tmp_path)
    assert len(reviews["reviews"]) == 1
    assert reviews["reviews"][0]["invoice_id"] == invoice_id
    assert reviews["reviews"][0]["payment_metadata_is_gate_authority"] is False

    admin_auth = authenticate_admin_headers({"authorization": "Bearer admin-secret"}, env={"SEMEAI_GATE_ADMIN_KEY": "admin-secret"})
    activation = activate_workspace_after_manual_review(
        verified["workspace_id"],
        {"invoice_id": invoice_id, "activation_note": "manual TRC20 payment verified"},
        account_dir=tmp_path,
        admin_auth=admin_auth,
    )
    assert activation["status"] == "activated"
    assert activation["workspace"]["billing"]["payment_status"] == "paid"
    assert activation["workspace"]["billing"]["manual_review_required"] is False

    result = check_api_answer(
        FAKE_PROMO_REQUEST,
        headers={"authorization": f"Bearer {verified['api_key']}"},
        receipt_dir=tmp_path / "receipts",
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )
    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["show_to_user"] is False


def test_http_admin_review_and_activation_flow(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "static-admin")
    monkeypatch.setenv("SEMEAI_GATE_ADMIN_KEY", "admin-secret")
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        registration = _post_json(
            f"{base}/v0/register",
            {
                "email": "operator@example.com",
                "password": "secure-pass-99",
                "company": "Operator Pilot",
            },
            expected_status=201,
        )
        token = registration["verification"]["verification_url"].split("#verify=", 1)[1]
        verified = _post_json(f"{base}/v0/verify", {"verification_token": token})
        api_headers = {"Authorization": f"Bearer {verified['api_key']}"}

        intent = _post_json(f"{base}/v0/billing/manual-crypto-intent", {"amount_usdt": "25.00"}, headers=api_headers, expected_status=201)
        invoice_id = intent["invoice"]["invoice_id"]
        _post_json(f"{base}/v0/billing/submit-txid", {"invoice_id": invoice_id, "txid": TXID}, headers=api_headers)

        unauthorized = _get_json_error(f"{base}/v0/admin/billing-reviews", headers={"Authorization": "Bearer wrong"})
        assert unauthorized["status"] == 403

        reviews = _get_json(f"{base}/v0/admin/billing-reviews", headers={"Authorization": "Bearer admin-secret"})
        assert reviews["reviews"][0]["invoice_id"] == invoice_id

        activation = _post_json(
            f"{base}/v0/admin/workspaces/{verified['workspace_id']}/activate",
            {"invoice_id": invoice_id, "activation_note": "manual review complete"},
            headers={"Authorization": "Bearer admin-secret"},
        )
        assert activation["status"] == "activated"
        assert activation["workspace"]["billing"]["payment_status"] == "paid"
        assert activation["invariants"][0] == "payment_metadata_is_not_gate_authority"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _verified_workspace(root: Path) -> dict[str, Any]:
    registration = register_workspace(
        {"email": "pilot@example.com", "password": "secure-pass-99", "company": "Pilot"},
        account_dir=root,
    )
    token = registration["verification"]["verification_url"].split("#verify=", 1)[1]
    return verify_registration(token, account_dir=root)


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


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _get_json_error(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return {"status": exc.status, "body": json.loads(exc.read().decode("utf-8"))}
    raise AssertionError("expected HTTP error")
