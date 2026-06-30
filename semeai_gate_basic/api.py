from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .gate import SCHEMA_VERSION, check_ai_answer


API_VERSION = "0.1"
DEFAULT_RECEIPT_DIR = Path("outputs") / "api_receipts"


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
) -> dict[str, Any]:
    target = Path(receipt_dir or DEFAULT_RECEIPT_DIR)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if not target.exists():
        return {"receipt_dir": str(target), "receipts": [], "count": 0}

    receipts: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
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
                "path": str(path),
            }
        )
    return {"receipt_dir": str(target), "receipts": receipts, "count": len(receipts)}


def read_receipt(
    receipt_id: str,
    *,
    receipt_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    target = Path(receipt_dir or DEFAULT_RECEIPT_DIR)
    if not receipt_id or not target.exists():
        return None
    for path in target.glob(f"*{receipt_id}*.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if receipt.get("receipt_id") == receipt_id:
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
