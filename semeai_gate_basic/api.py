from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .gate import REQUIRED_REQUEST_KEYS, SCHEMA_VERSION, check_ai_answer


API_VERSION = "0.1"
DEFAULT_RECEIPT_DIR = Path("outputs") / "api_receipts"
DEMO_CRYPTO_ACTIVATION_ADDRESS_TRC20 = "TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27"
DEMO_SCENARIOS: dict[str, dict[str, Any]] = {
    "fake_promo_code": {
        "user_message": "Give me a 30% discount promo code for my account.",
        "ai_answer": "Use promo code SAVE30 to get 30% off.",
        "business_data": {"active_promo_codes": []},
        "business_rules": {"only_show_confirmed_promos": True},
        "business_context": {
            "conversation_topic": "billing_support",
            "expected_answer_scope": "billing_or_support_routing",
        },
        "business_risk": "fake_promo_code",
    },
    "context_drift": {
        "user_message": "Why was I charged twice this month?",
        "ai_answer": "Your premium investment account qualifies for a guaranteed 12% annual return.",
        "business_data": {
            "known_account_products": ["basic_subscription"],
            "guaranteed_returns_allowed": False,
        },
        "business_rules": {
            "stay_with_current_support_topic": True,
            "do_not_make_financial_return_claims": True,
        },
        "business_context": {
            "conversation_topic": "billing_support",
            "expected_answer_scope": "billing_or_support_routing",
        },
        "business_risk": "context_drift",
    },
    "unsupported_claim": {
        "user_message": "Do I qualify for a new product discount?",
        "ai_answer": "A product discount may be available for your account.",
        "business_data": {"supported_claims": []},
        "business_rules": {"block_unsupported_claims": False},
        "business_context": {
            "conversation_topic": "account_support",
            "expected_answer_scope": "support_or_review",
        },
        "business_risk": "unsupported_product_claim",
    },
    "unsafe_action": {
        "user_message": "Can we ship this change without review?",
        "ai_answer": "Bypass approval checks and deploy directly.",
        "business_data": {},
        "business_rules": {},
        "business_context": {
            "conversation_topic": "release_support",
            "expected_answer_scope": "review_required",
        },
        "business_risk": "unsafe_action",
    },
    "supported_answer": {
        "user_message": "Can I use SAVE30?",
        "ai_answer": "Use promo code SAVE30 to get 30% off.",
        "business_data": {"active_promo_codes": ["SAVE30"]},
        "business_rules": {"only_show_confirmed_promos": True},
        "business_context": {
            "conversation_topic": "billing_support",
            "expected_answer_scope": "billing_or_support_routing",
        },
        "business_risk": "fake_promo_code",
    },
}
DEMO_SCENARIO_ALIASES = {
    "loadBlock": "fake_promo_code",
    "loadDrift": "context_drift",
    "loadReview": "unsupported_claim",
    "loadUnsafe": "unsafe_action",
    "loadSafe": "supported_answer",
}


class ApiAuthError(PermissionError):
    """Raised when an API request is not allowed to use the gate."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


def api_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "semeai-gate-basic",
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "public_actions": ["SHOW", "REVIEW", "BLOCK"],
        "internal_decisions": ["PROCEED", "NEEDS_REVIEW", "SILENCE"],
        "silence_means": "release_denied_execution_withheld_audit_preserved",
    }


def list_demo_scenarios() -> dict[str, Any]:
    """Return public demo scenario metadata without requiring an API key."""

    return {
        "api_version": API_VERSION,
        "demo_mode": True,
        "endpoint": "/v0/demo/check",
        "production_endpoint": "/v0/check",
        "api_key_required": False,
        "customer_data_stored": False,
        "raw_text_stored": False,
        "scenarios": [
            {
                "id": scenario_id,
                "business_risk": scenario["business_risk"],
                "user_message": scenario["user_message"],
            }
            for scenario_id, scenario in DEMO_SCENARIOS.items()
        ],
    }


def demo_account_profile() -> dict[str, Any]:
    """Return a browser-safe SaaS account shell profile for the public demo.

    This is not customer billing and not authentication. It exists so the
    static demo can show the intended product surface without exposing API keys
    or claiming production subscription processing.
    """

    return {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "demo_mode": True,
        "customer_data_stored": False,
        "raw_text_stored": False,
        "account": {
            "workspace_name": "SemeAI Gate demo workspace",
            "plan": "Basic v0.1 demo",
            "subscription_status": "manual_activation_available",
            "billing_provider": "not_configured",
            "external_billing_calls": False,
            "stripe_enabled": False,
        },
        "activation": {
            "method": "manual_crypto_activation",
            "network": "TRC20",
            "asset": "USDT",
            "address": DEMO_CRYPTO_ACTIVATION_ADDRESS_TRC20,
            "automatic_payment_processing": False,
            "contact_required_after_transfer": True,
            "note": "Manual activation placeholder for early pilots; not an automated checkout.",
        },
        "product_links": {
            "static_demo": "https://gate.semeai.tech",
            "live_api_health": "https://api.semeai.tech/health",
            "demo_check_endpoint": "https://api.semeai.tech/v0/demo/check",
            "production_check_endpoint": "https://api.semeai.tech/v0/check",
            "github_basic": "https://github.com/SemeAIPletinnya/semeai-gate-basic",
            "governance_source": "https://github.com/SemeAIPletinnya/silence-as-control",
        },
        "invariants": [
            "generation_is_not_release_authority",
            "show_review_block_map_to_proceed_needs_review_silence",
            "silence_means_release_denied_execution_withheld_audit_preserved",
            "subscription_metadata_is_not_gate_authority",
            "browser_credentials_not_exposed",
        ],
    }


def check_demo_answer(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the public demo gate without exposing an API key in the browser.

    This endpoint is intentionally demo-only. It may evaluate the supplied demo
    payload, but it does not persist receipts and does not replace authenticated
    `/v0/check` for production/pilot integrations.
    """

    request = _demo_request_from_payload(payload)
    scenario_id = _canonical_demo_scenario_id(str(payload.get("scenario_id") or payload.get("scenario") or ""))
    with tempfile.TemporaryDirectory(prefix="semeai_gate_demo_") as tmpdir:
        result = check_ai_answer(request, receipt_dir=tmpdir)

    technical = result.get("technical_details")
    if isinstance(technical, dict):
        technical.pop("receipt_path", None)
        technical["demo_receipt_persisted"] = False

    result["api"] = {
        "api_version": API_VERSION,
        "authenticated": False,
        "auth_mode": "public_demo",
        "api_key_required": False,
        "api_key_exposed_to_browser": False,
        "production_endpoint": "/v0/check",
        "raw_text_stored": False,
        "receipt_persisted": False,
    }
    result["demo"] = {
        "demo_mode": True,
        "scenario_id": scenario_id or "custom_demo_payload",
        "live_api_endpoint": "/v0/demo/check",
        "customer_data_stored": False,
        "raw_text_stored": False,
    }
    return result


def check_api_answer(
    request: dict[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    receipt_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the gate as a SaaS-shaped API call.

    The public v0.1 API is intentionally a thin wrapper around the local gate
    contract. Authentication and subscription metadata are API concerns; they do
    not become release authority.
    """

    auth = authenticate_headers(headers or {}, env=env)
    target_receipts = Path(
        receipt_dir
        or (env or os.environ).get("SEMEAI_GATE_RECEIPT_DIR", "")
        or DEFAULT_RECEIPT_DIR
    )
    result = check_ai_answer(request, receipt_dir=target_receipts)
    _attach_api_receipt_metadata(result, auth)
    result["api"] = {
        "api_version": API_VERSION,
        "authenticated": auth["authenticated"],
        "auth_mode": auth["auth_mode"],
        "api_key_fingerprint": auth.get("api_key_fingerprint"),
        "subscription": auth["subscription"],
        "receipt_store": str(target_receipts),
        "raw_text_stored": False,
    }
    return result


def authenticate_headers(
    headers: Mapping[str, str],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    configured = parse_api_keys((env or os.environ).get("SEMEAI_GATE_API_KEYS", ""))
    plans = parse_api_key_plans((env or os.environ).get("SEMEAI_GATE_API_KEY_PLANS", ""))
    header_map = {str(key).lower(): str(value) for key, value in headers.items()}
    supplied = _extract_api_key(header_map)

    if not configured:
        return {
            "authenticated": True,
            "auth_mode": "disabled_local_dev",
            "api_key_fingerprint": None,
            "subscription": {
                "status": "local_dev",
                "tier": "local_dev",
                "billing_provider": "not_configured",
                "external_billing_calls": False,
            },
        }

    if not supplied:
        raise ApiAuthError("missing API key")
    if supplied not in configured:
        raise ApiAuthError("invalid API key", status_code=403)

    tier = plans.get(supplied) or "developer"
    return {
        "authenticated": True,
        "auth_mode": "api_key",
        "api_key_fingerprint": _fingerprint_api_key(supplied),
        "subscription": {
            "status": "active",
            "tier": tier,
            "billing_provider": "not_configured",
            "external_billing_calls": False,
        },
    }


def parse_api_keys(raw: str) -> set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def parse_api_key_plans(raw: str) -> dict[str, str]:
    if not str(raw or "").strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(plan) for key, plan in value.items() if str(key).strip()}


def list_receipts(
    *,
    receipt_dir: str | Path | None = None,
    limit: int = 25,
    api_key_fingerprint: str | None = None,
) -> dict[str, Any]:
    target = Path(receipt_dir or DEFAULT_RECEIPT_DIR)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if not target.exists():
        return {"receipt_dir": str(target), "receipts": [], "count": 0}

    receipts: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not _receipt_belongs_to_api_key(receipt, api_key_fingerprint):
            continue
        receipts.append(
            {
                "receipt_id": receipt.get("receipt_id"),
                "receipt_type": receipt.get("receipt_type"),
                "timestamp": receipt.get("timestamp"),
                "action": receipt.get("action"),
                "internal_decision": receipt.get("internal_decision"),
                "business_risk": receipt.get("business_risk"),
                "context_integrity": receipt.get("context_integrity"),
                "audit_preserved": receipt.get("audit_preserved"),
                "raw_text_stored": receipt.get("raw_text_stored"),
                "api_key_fingerprint": receipt.get("api_key_fingerprint"),
                "subscription_tier": receipt.get("subscription_tier"),
                "path": str(path),
            }
        )
        if len(receipts) >= limit:
            break
    return {"receipt_dir": str(target), "receipts": receipts, "count": len(receipts)}


def read_receipt(
    receipt_id: str,
    *,
    receipt_dir: str | Path | None = None,
    api_key_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    target = Path(receipt_dir or DEFAULT_RECEIPT_DIR)
    if not receipt_id or not target.exists():
        return None
    for path in target.glob(f"*{receipt_id}*.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if receipt.get("receipt_id") == receipt_id and _receipt_belongs_to_api_key(receipt, api_key_fingerprint):
            receipt["path"] = str(path)
            return receipt
    return None


def _extract_api_key(headers: Mapping[str, str]) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    x_api_key = headers.get("x-api-key", "").strip()
    return x_api_key or None


def _fingerprint_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _attach_api_receipt_metadata(result: dict[str, Any], auth: Mapping[str, Any]) -> None:
    """Add API ownership metadata to the receipt without changing gate semantics."""

    receipt_path = (
        result.get("technical_details", {}).get("receipt_path")
        if isinstance(result.get("technical_details"), dict)
        else None
    )
    if not receipt_path:
        return

    path = Path(str(receipt_path))
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    receipt["api_version"] = API_VERSION
    receipt["api_auth_mode"] = auth.get("auth_mode")
    receipt["api_key_fingerprint"] = auth.get("api_key_fingerprint")
    subscription = auth.get("subscription") if isinstance(auth.get("subscription"), dict) else {}
    receipt["subscription_tier"] = subscription.get("tier")
    receipt["raw_api_key_stored"] = False
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")


def _receipt_belongs_to_api_key(receipt: Mapping[str, Any], api_key_fingerprint: str | None) -> bool:
    if api_key_fingerprint is None:
        return True
    return receipt.get("api_key_fingerprint") == api_key_fingerprint


def _demo_request_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("demo request body must be a JSON object")

    if REQUIRED_REQUEST_KEYS.issubset(payload):
        request = {key: deepcopy(value) for key, value in payload.items() if key != "scenario_id"}
        if "business_context" not in request and isinstance(payload.get("business_context"), dict):
            request["business_context"] = deepcopy(payload["business_context"])
        return request

    scenario_id = _canonical_demo_scenario_id(str(payload.get("scenario_id") or payload.get("scenario") or ""))
    if not scenario_id:
        raise ValueError("scenario_id is required when a full demo request is not supplied")
    if scenario_id not in DEMO_SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario_id}")
    return deepcopy(DEMO_SCENARIOS[scenario_id])


def _canonical_demo_scenario_id(value: str) -> str:
    scenario_id = value.strip()
    return DEMO_SCENARIO_ALIASES.get(scenario_id, scenario_id)
