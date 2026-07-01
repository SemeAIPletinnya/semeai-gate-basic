from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from semeai_gate_basic.api import (
    ApiAuthError,
    authenticate_headers,
    check_api_answer,
    check_demo_answer,
    list_receipts,
    list_demo_scenarios,
    parse_api_key_plans,
    parse_api_keys,
    read_receipt,
)
from semeai_gate_basic.server import SemeAIGateHandler
from semeai_gate_basic.server import validate_server_auth_config


FAKE_PROMO_REQUEST = {
    "user_message": "Give me a 30% discount promo code for my account.",
    "ai_answer": "Use promo code SAVE30 to get 30% off.",
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_context": {
        "conversation_topic": "billing_support",
        "active_promotions_available": False,
    },
    "business_risk": "fake_promo_code",
}


def test_parse_api_key_config() -> None:
    assert parse_api_keys("alpha, beta ,,gamma") == {"alpha", "beta", "gamma"}
    assert parse_api_key_plans('{"alpha":"developer","beta":"pilot"}') == {
        "alpha": "developer",
        "beta": "pilot",
    }
    assert parse_api_key_plans("not json") == {}


def test_api_key_auth_disabled_local_dev() -> None:
    auth = authenticate_headers({}, env={})

    assert auth["authenticated"] is True
    assert auth["auth_mode"] == "disabled_local_dev"
    assert auth["subscription"]["tier"] == "local_dev"
    assert auth["subscription"]["external_billing_calls"] is False


def test_api_key_auth_requires_key_when_configured() -> None:
    with pytest.raises(ApiAuthError):
        authenticate_headers({}, env={"SEMEAI_GATE_API_KEYS": "secret"})


def test_api_key_auth_accepts_bearer_and_subscription_plan() -> None:
    auth = authenticate_headers(
        {"authorization": "Bearer secret"},
        env={
            "SEMEAI_GATE_API_KEYS": "secret",
            "SEMEAI_GATE_API_KEY_PLANS": '{"secret":"pilot"}',
        },
    )

    assert auth["auth_mode"] == "api_key"
    assert auth["api_key_fingerprint"]
    assert auth["subscription"]["status"] == "active"
    assert auth["subscription"]["tier"] == "pilot"
    assert auth["subscription"]["billing_provider"] == "not_configured"


def test_check_api_answer_writes_receipt_without_raw_text(tmp_path: Path) -> None:
    result = check_api_answer(
        FAKE_PROMO_REQUEST,
        headers={"authorization": "Bearer secret"},
        receipt_dir=tmp_path,
        env={"SEMEAI_GATE_API_KEYS": "secret"},
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["api"]["authenticated"] is True
    assert result["api"]["subscription"]["tier"] == "developer"

    receipts = list_receipts(receipt_dir=tmp_path)
    assert receipts["count"] == 1
    assert receipts["receipts"][0]["receipt_id"] == result["audit_id"]
    receipt = read_receipt(result["audit_id"], receipt_dir=tmp_path)
    assert receipt is not None
    assert receipt["raw_text_stored"] is False
    serialized = json.dumps(receipt)
    assert FAKE_PROMO_REQUEST["user_message"] not in serialized
    assert FAKE_PROMO_REQUEST["ai_answer"] not in serialized
    assert "secret" not in serialized
    assert receipt["api_key_fingerprint"] == result["api"]["api_key_fingerprint"]
    assert receipt["raw_api_key_stored"] is False


def test_public_demo_scenarios_are_listed_without_secrets() -> None:
    listing = list_demo_scenarios()

    assert listing["demo_mode"] is True
    assert listing["api_key_required"] is False
    assert listing["customer_data_stored"] is False
    assert {item["id"] for item in listing["scenarios"]} >= {
        "fake_promo_code",
        "context_drift",
        "unsupported_claim",
        "unsafe_action",
        "supported_answer",
    }
    serialized = json.dumps(listing)
    assert "authorization" not in serialized.lower()
    assert "api_key" in serialized


def test_public_demo_check_does_not_require_or_persist_api_receipt() -> None:
    result = check_demo_answer({"scenario_id": "fake_promo_code"})

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["api"]["auth_mode"] == "public_demo"
    assert result["api"]["api_key_required"] is False
    assert result["api"]["api_key_exposed_to_browser"] is False
    assert result["api"]["receipt_persisted"] is False
    assert result["demo"]["scenario_id"] == "fake_promo_code"
    assert "receipt_path" not in result["technical_details"]


def test_public_demo_check_accepts_full_demo_payload_without_auth() -> None:
    result = check_demo_answer({**FAKE_PROMO_REQUEST, "scenario_id": "loadBlock"})

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["api"]["auth_mode"] == "public_demo"
    assert result["api"]["raw_text_stored"] is False


def test_public_demo_check_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError):
        check_demo_answer({"scenario_id": "not_a_scenario"})


def test_api_receipts_are_scoped_to_authenticated_key(tmp_path: Path) -> None:
    first = check_api_answer(
        FAKE_PROMO_REQUEST,
        headers={"authorization": "Bearer alpha"},
        receipt_dir=tmp_path,
        env={"SEMEAI_GATE_API_KEYS": "alpha,beta"},
    )
    second = check_api_answer(
        {**FAKE_PROMO_REQUEST, "business_risk": "unsupported_financial_claim"},
        headers={"authorization": "Bearer beta"},
        receipt_dir=tmp_path,
        env={"SEMEAI_GATE_API_KEYS": "alpha,beta"},
    )

    first_fingerprint = first["api"]["api_key_fingerprint"]
    second_fingerprint = second["api"]["api_key_fingerprint"]

    unscoped = list_receipts(receipt_dir=tmp_path)
    assert unscoped["count"] == 2

    first_receipts = list_receipts(receipt_dir=tmp_path, api_key_fingerprint=first_fingerprint)
    assert first_receipts["count"] == 1
    assert first_receipts["receipts"][0]["receipt_id"] == first["audit_id"]
    assert first_receipts["receipts"][0]["api_key_fingerprint"] == first_fingerprint

    second_receipts = list_receipts(receipt_dir=tmp_path, api_key_fingerprint=second_fingerprint)
    assert second_receipts["count"] == 1
    assert second_receipts["receipts"][0]["receipt_id"] == second["audit_id"]

    assert read_receipt(first["audit_id"], receipt_dir=tmp_path, api_key_fingerprint=first_fingerprint)
    assert read_receipt(second["audit_id"], receipt_dir=tmp_path, api_key_fingerprint=first_fingerprint) is None


def test_invalid_api_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ApiAuthError):
        check_api_answer(
            FAKE_PROMO_REQUEST,
            headers={"authorization": "Bearer wrong"},
            receipt_dir=tmp_path,
            env={"SEMEAI_GATE_API_KEYS": "secret"},
        )


def test_http_server_check_and_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "secret")
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path))

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        result = _post_json(
            f"{base}/v0/check",
            FAKE_PROMO_REQUEST,
            headers={"Authorization": "Bearer secret"},
        )
        assert result["action"] == "BLOCK"
        assert result["internal_decision"] == "SILENCE"
        assert result["api"]["auth_mode"] == "api_key"

        receipts = _get_json(f"{base}/v0/receipts?limit=5", headers={"Authorization": "Bearer secret"})
        assert receipts["count"] == 1
        assert receipts["receipts"][0]["receipt_id"] == result["audit_id"]

        demo_result = _post_json(f"{base}/v0/demo/check", {"scenario_id": "fake_promo_code"})
        assert demo_result["action"] == "BLOCK"
        assert demo_result["api"]["auth_mode"] == "public_demo"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_server_rejects_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "secret")
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path))

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _post_json(f"{base}/v0/check", FAKE_PROMO_REQUEST)
        assert exc_info.value.code == 401

        demo_result = _post_json(f"{base}/v0/demo/check", {"scenario_id": "fake_promo_code"})
        assert demo_result["action"] == "BLOCK"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_server_head_health_returns_security_headers() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = urllib.request.Request(f"{base}/health", method="HEAD")
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
            assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read() == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_public_bind_requires_api_keys() -> None:
    validate_server_auth_config("127.0.0.1", env={})
    validate_server_auth_config("localhost", env={})
    validate_server_auth_config("0.0.0.0", env={"SEMEAI_GATE_API_KEYS": "secret"})
    validate_server_auth_config("0.0.0.0", env={"SEMEAI_GATE_API_KEYS": "alpha,,beta"})

    with pytest.raises(RuntimeError):
        validate_server_auth_config("0.0.0.0", env={})

    with pytest.raises(RuntimeError):
        validate_server_auth_config("192.168.1.10", env={})

    with pytest.raises(RuntimeError):
        validate_server_auth_config("0.0.0.0", env={"SEMEAI_GATE_API_KEYS": ",, ,"})


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"content-type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
