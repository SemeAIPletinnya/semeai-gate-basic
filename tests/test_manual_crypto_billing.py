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

from semeai_gate_basic.accounts import register_workspace, verify_registration
from semeai_gate_basic.api import authenticate_headers, check_api_answer
from semeai_gate_basic.billing import (
    BillingError,
    billing_status,
    create_manual_crypto_intent,
    submit_manual_crypto_txid,
)
from semeai_gate_basic.server import SemeAIGateHandler


TRC20_ADDRESS = "TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27"
VALID_TXID = "a" * 64
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


def test_verified_workspace_has_manual_billing_metadata(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)

    assert verified["billing"]["status"] == "trial"
    assert verified["billing"]["payment_status"] == "unpaid"
    assert verified["billing"]["billing_provider"] == "manual_usdt_trc20"
    assert verified["billing"]["network"] == "TRC20"
    assert verified["billing"]["asset"] == "USDT"
    assert verified["billing"]["manual_review_required"] is True
    assert verified["billing"]["automatic_onchain_verification"] is True
    workspace = _load_only_workspace(tmp_path)
    assert "payment_is_never_gate_authority" in workspace["invariants"]
    assert verified["billing"]["external_billing_calls"] is False
    assert verified["billing"]["private_keys_stored"] is False


def test_create_manual_crypto_intent_records_invoice_without_activation(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)
    auth = _auth_for_key(tmp_path, verified["api_key"])

    result = create_manual_crypto_intent(
        auth,
        {"plan": "pilot", "amount_usdt": "25"},
        account_dir=tmp_path,
        env={"SEMEAI_GATE_USDT_TRC20_ADDRESS": TRC20_ADDRESS},
    )

    invoice = result["invoice"]
    assert result["status"] == "created"
    assert result["billing"]["status"] == "pending_payment"
    assert invoice["payment_address"] == TRC20_ADDRESS
    assert invoice["amount_usdt"] == "25.00"
    assert invoice["payment_status"] == "pending_payment"
    assert invoice["automatic_onchain_verification"] is False
    assert invoice["private_keys_stored"] is False
    assert invoice["external_billing_calls"] is False

    invoice_path = tmp_path / "billing_intents" / f"{invoice['invoice_id']}.json"
    assert invoice_path.exists()
    workspace = _load_only_workspace(tmp_path)
    assert workspace["billing"]["status"] == "pending_payment"
    assert workspace["billing"]["latest_invoice_id"] == invoice["invoice_id"]


def test_submit_txid_moves_to_pending_review_not_paid_active(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)
    auth = _auth_for_key(tmp_path, verified["api_key"])
    intent = create_manual_crypto_intent(auth, {"amount_usdt": "25"}, account_dir=tmp_path)

    result = submit_manual_crypto_txid(
        auth,
        {"invoice_id": intent["invoice"]["invoice_id"], "txid": VALID_TXID},
        account_dir=tmp_path,
    )

    assert result["status"] == "pending_review"
    assert result["payment_status"] == "pending_review"
    assert result["manual_review_required"] is True
    # On-chain lookup may run (TronGrid) but never auto-activates paid access.
    assert result["audit_preserved"] is True
    assert "txid_hash" in result
    assert "txid" not in result
    assert "onchain" in result

    workspace = _load_only_workspace(tmp_path)
    assert workspace["billing"]["status"] == "pending_review"
    assert workspace["billing"]["payment_status"] == "pending_review"
    assert workspace["subscription"]["status"] == "trial"
    assert workspace["subscription"]["tier"] == "free"
    assert workspace["billing"]["manual_review_required"] is True


def test_invalid_txid_is_rejected_without_activation(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)
    auth = _auth_for_key(tmp_path, verified["api_key"])
    intent = create_manual_crypto_intent(auth, {"amount_usdt": "25"}, account_dir=tmp_path)

    with pytest.raises(BillingError):
        submit_manual_crypto_txid(auth, {"invoice_id": intent["invoice"]["invoice_id"], "txid": "not-a-txid"}, account_dir=tmp_path)

    workspace = _load_only_workspace(tmp_path)
    assert workspace["billing"]["status"] == "pending_payment"


def test_manual_billing_requires_issued_workspace_key(tmp_path: Path) -> None:
    static_auth = authenticate_headers(
        {"authorization": "Bearer static-admin"},
        env={"SEMEAI_GATE_API_KEYS": "static-admin"},
    )

    with pytest.raises(BillingError) as exc_info:
        create_manual_crypto_intent(static_auth, {"amount_usdt": "25"}, account_dir=tmp_path)

    assert exc_info.value.status_code == 403


def test_billing_metadata_does_not_change_gate_decision(tmp_path: Path) -> None:
    verified = _verified_workspace(tmp_path)
    auth = _auth_for_key(tmp_path, verified["api_key"])
    intent = create_manual_crypto_intent(auth, {"amount_usdt": "25"}, account_dir=tmp_path)
    submit_manual_crypto_txid(auth, {"invoice_id": intent["invoice"]["invoice_id"], "txid": VALID_TXID}, account_dir=tmp_path)

    result = check_api_answer(
        FAKE_PROMO_REQUEST,
        headers={"authorization": f"Bearer {verified['api_key']}"},
        receipt_dir=tmp_path / "receipts",
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["show_to_user"] is False


def test_http_billing_endpoints_are_scoped_and_pending_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account_dir = tmp_path / "accounts"
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(account_dir))
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "static-admin")
    monkeypatch.setenv("SEMEAI_GATE_USDT_TRC20_ADDRESS", TRC20_ADDRESS)

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        registration = _post_json(
            f"{base}/v0/register",
            {"email": "pilot@example.com", "password": "secure-pass-99", "company": "Pilot"},
            expected_status=201,
        )
        verified = _post_json(f"{base}/v0/verify", {"verification_token": _token_from_url(registration["verification"]["verification_url"])})
        headers = {"Authorization": f"Bearer {verified['api_key']}"}

        status = _get_json(f"{base}/v0/billing/status", headers=headers)
        assert status["manual_crypto"]["payment_address"] == TRC20_ADDRESS
        assert status["manual_crypto"]["private_keys_stored"] is False

        intent = _post_json(f"{base}/v0/billing/manual-crypto-intent", {"amount_usdt": "25.00"}, headers=headers, expected_status=201)
        assert intent["invoice"]["payment_status"] == "pending_payment"

        proof = _post_json(
            f"{base}/v0/billing/submit-txid",
            {"invoice_id": intent["invoice"]["invoice_id"], "txid": VALID_TXID},
            headers=headers,
        )
        assert proof["status"] == "pending_review"
        assert proof["manual_review_required"] is True

        account = _get_json(f"{base}/v0/account", headers=headers)
        assert account["billing"]["status"] == "pending_review"
        assert account["manual_crypto"]["automatic_onchain_verification"] is False

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _post_json(f"{base}/v0/billing/manual-crypto-intent", {"amount_usdt": "25.00"}, headers={"Authorization": "Bearer static-admin"})
        assert exc_info.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _verified_workspace(root: Path) -> dict[str, Any]:
    registration = register_workspace(
        {"email": "pilot@example.com", "password": "secure-pass-99", "company": "Pilot"},
        account_dir=root,
    )
    return verify_registration(_token_from_url(registration["verification"]["verification_url"]), account_dir=root)


def _auth_for_key(root: Path, api_key: str) -> dict[str, Any]:
    return authenticate_headers(
        {"authorization": f"Bearer {api_key}"},
        env={"SEMEAI_GATE_ACCOUNT_DIR": str(root), "SEMEAI_GATE_API_KEYS": "static-admin"},
    )


def _load_only_workspace(root: Path) -> dict[str, Any]:
    workspace_files = list((root / "workspaces").glob("*.json"))
    assert len(workspace_files) == 1
    return json.loads(workspace_files[0].read_text(encoding="utf-8"))


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


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
