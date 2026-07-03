from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping


ADMIN_SCHEMA_VERSION = "0.1-admin"
DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"


class AdminAuthError(PermissionError):
    """Raised when an operator/admin endpoint is not authorized."""

    def __init__(self, message: str, *, status_code: int = HTTPStatus.UNAUTHORIZED) -> None:
        super().__init__(message)
        self.status_code = status_code


class AdminActionError(ValueError):
    """Raised when an operator/admin action cannot be completed safely."""

    def __init__(self, message: str, *, status_code: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status_code = status_code


def authenticate_admin_headers(
    headers: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Authenticate a narrow operator/admin API key.

    This key is only for account/billing administration. It is not a gate key and
    does not change release authority.
    """

    values = env or os.environ
    configured_key = str(values.get("SEMEAI_GATE_ADMIN_KEY") or "").strip()
    if not configured_key:
        raise AdminAuthError("admin key is not configured", status_code=HTTPStatus.SERVICE_UNAVAILABLE)

    supplied_key = _extract_admin_key(headers)
    if not supplied_key:
        raise AdminAuthError("admin authorization is required", status_code=HTTPStatus.UNAUTHORIZED)
    if not hmac.compare_digest(supplied_key, configured_key):
        raise AdminAuthError("invalid admin authorization", status_code=HTTPStatus.FORBIDDEN)

    return {
        "authenticated": True,
        "auth_mode": "admin_api_key",
        "admin_key_fingerprint": _fingerprint(supplied_key),
        "admin_is_release_authority": False,
        "payment_metadata_is_gate_authority": False,
    }


def list_admin_workspaces(
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    root = _account_root(account_dir=account_dir, env=env)
    workspaces_dir = root / "workspaces"
    records: list[dict[str, Any]] = []
    if workspaces_dir.exists():
        for path in sorted(workspaces_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            record = _read_json(path)
            if isinstance(record, dict):
                records.append(_workspace_summary(record))
            if len(records) >= max(1, min(limit, 200)):
                break

    return {
        "schema_version": ADMIN_SCHEMA_VERSION,
        "admin_mode": True,
        "release_authority_changed": False,
        "workspaces": records,
    }


def list_billing_reviews(
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    root = _account_root(account_dir=account_dir, env=env)
    proofs_dir = root / "billing_proofs"
    reviews: list[dict[str, Any]] = []
    if proofs_dir.exists():
        for path in sorted(proofs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            proof = _read_json(path)
            if not isinstance(proof, dict):
                continue
            if proof.get("payment_status") not in {"pending_review", "submitted"}:
                continue
            workspace = _read_workspace(root, str(proof.get("workspace_id") or ""))
            invoice = _read_invoice(root, str(proof.get("invoice_id") or ""))
            reviews.append(
                {
                    "schema_version": ADMIN_SCHEMA_VERSION,
                    "invoice_id": proof.get("invoice_id"),
                    "workspace_id": proof.get("workspace_id"),
                    "workspace": _workspace_summary(workspace) if workspace else None,
                    "payment_status": proof.get("payment_status"),
                    "billing_status": proof.get("billing_status"),
                    "txid": proof.get("txid"),
                    "txid_hash": proof.get("txid_hash"),
                    "raw_txid_stored": bool(proof.get("raw_txid_stored")),
                    "amount_usdt": invoice.get("amount_usdt") if invoice else None,
                    "asset": invoice.get("asset") if invoice else "USDT",
                    "network": invoice.get("network") if invoice else "TRC20",
                    "submitted_at": proof.get("submitted_at"),
                    "operator_note": proof.get("operator_note"),
                    "manual_review_required": True,
                    "automatic_onchain_verification": False,
                    "payment_metadata_is_gate_authority": False,
                }
            )
            if len(reviews) >= max(1, min(limit, 200)):
                break

    return {
        "schema_version": ADMIN_SCHEMA_VERSION,
        "admin_mode": True,
        "manual_review_required": True,
        "automatic_onchain_verification": False,
        "reviews": reviews,
    }


def activate_workspace_after_manual_review(
    workspace_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    admin_auth: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a workspace as paid after manual operator review.

    This activates account metadata only. It is not release authority and does
    not change any SaC/PoR decision semantics.
    """

    root = _account_root(account_dir=account_dir, env=env)
    workspace_path = root / "workspaces" / f"{_clean_id(workspace_id)}.json"
    workspace = _read_json(workspace_path)
    if not isinstance(workspace, dict):
        raise AdminActionError("workspace not found", status_code=HTTPStatus.NOT_FOUND)

    request = payload or {}
    invoice_id = _clean_id(request.get("invoice_id") or workspace.get("billing", {}).get("latest_invoice_id") or "")
    if not invoice_id:
        raise AdminActionError("invoice_id is required for manual activation")
    invoice = _read_invoice(root, invoice_id)
    if not invoice:
        raise AdminActionError("invoice not found", status_code=HTTPStatus.NOT_FOUND)
    if invoice.get("workspace_id") != workspace.get("workspace_id"):
        raise AdminActionError("invoice does not belong to this workspace", status_code=HTTPStatus.FORBIDDEN)

    activated_at = _now()
    activated_by = str((admin_auth or {}).get("admin_key_fingerprint") or "admin")
    activation_note = _clean_text(request.get("activation_note") or request.get("note") or "", max_len=500)
    plan = _clean_text(request.get("plan") or invoice.get("plan") or workspace.get("plan") or "pilot")

    invoice.update(
        {
            "payment_status": "paid",
            "billing_status": "active",
            "manual_review_required": False,
            "manual_review_completed": True,
            "activated_at": activated_at,
            "activated_by": activated_by,
            "activation_note": activation_note,
            "automatic_onchain_verification": False,
            "external_billing_calls": False,
        }
    )
    _write_json(root / "billing_intents" / f"{invoice_id}.json", invoice)

    billing = workspace.get("billing") if isinstance(workspace.get("billing"), dict) else {}
    billing.update(
        {
            "schema_version": "0.1-billing",
            "status": "active",
            "payment_status": "paid",
            "billing_provider": "manual_usdt_trc20",
            "plan": plan,
            "latest_invoice_id": invoice_id,
            "latest_amount_usdt": invoice.get("amount_usdt"),
            "network": invoice.get("network") or "TRC20",
            "asset": invoice.get("asset") or "USDT",
            "manual_review_required": False,
            "manual_review_completed": True,
            "automatic_onchain_verification": False,
            "external_billing_calls": False,
            "private_keys_stored": False,
            "activated_at": activated_at,
            "activated_by": activated_by,
            "activation_note": activation_note,
        }
    )
    workspace["billing"] = billing

    subscription = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
    subscription.update(
        {
            "status": "active",
            "tier": plan,
            "billing_provider": "manual_usdt_trc20",
            "manual_activation": True,
            "external_billing_calls": False,
            "activated_at": activated_at,
        }
    )
    workspace["subscription"] = subscription
    workspace["status"] = "active"
    workspace["updated_at"] = activated_at
    _write_json(workspace_path, workspace)

    _append_admin_event(
        root,
        {
            "event_type": "workspace_manual_payment_activated",
            "workspace_id": workspace.get("workspace_id"),
            "invoice_id": invoice_id,
            "admin_key_fingerprint": activated_by,
            "activated_at": activated_at,
            "payment_metadata_is_gate_authority": False,
            "release_authority_changed": False,
        },
    )

    return {
        "schema_version": ADMIN_SCHEMA_VERSION,
        "status": "activated",
        "workspace": _workspace_summary(workspace),
        "invoice_id": invoice_id,
        "activation": {
            "payment_status": "paid",
            "billing_status": "active",
            "manual_review_completed": True,
            "automatic_onchain_verification": False,
            "activated_at": activated_at,
        },
        "invariants": [
            "payment_metadata_is_not_gate_authority",
            "subscription_metadata_is_not_release_authority",
            "generation_is_not_release_authority",
            "show_review_block_map_to_proceed_needs_review_silence",
        ],
    }


def _extract_admin_key(headers: Mapping[str, Any]) -> str:
    values = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    auth = values.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return values.get("x-admin-key", "")


def _account_root(*, account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return Path(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)


def _read_workspace(root: Path, workspace_id: str) -> dict[str, Any] | None:
    value = _read_json(root / "workspaces" / f"{_clean_id(workspace_id)}.json")
    return value if isinstance(value, dict) else None


def _read_invoice(root: Path, invoice_id: str) -> dict[str, Any] | None:
    value = _read_json(root / "billing_intents" / f"{_clean_id(invoice_id)}.json")
    return value if isinstance(value, dict) else None


def _read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_admin_event(root: Path, event: Mapping[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": _now(), **dict(event)}
    with (root / "admin_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _workspace_summary(workspace: Mapping[str, Any]) -> dict[str, Any]:
    subscription = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
    billing = workspace.get("billing") if isinstance(workspace.get("billing"), dict) else {}
    return {
        "workspace_id": workspace.get("workspace_id"),
        "workspace_name": workspace.get("workspace_name"),
        "email": workspace.get("email"),
        "status": workspace.get("status"),
        "plan": workspace.get("plan") or subscription.get("tier") or billing.get("plan"),
        "subscription": {
            "status": subscription.get("status"),
            "tier": subscription.get("tier"),
            "billing_provider": subscription.get("billing_provider"),
            "external_billing_calls": False,
        },
        "billing": {
            "status": billing.get("status"),
            "payment_status": billing.get("payment_status"),
            "latest_invoice_id": billing.get("latest_invoice_id"),
            "manual_review_required": bool(billing.get("manual_review_required", True)),
            "automatic_onchain_verification": False,
            "external_billing_calls": False,
            "private_keys_stored": False,
        },
        "created_at": workspace.get("created_at"),
        "updated_at": workspace.get("updated_at"),
    }


def _clean_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in "\\/:*?\"<>|"):
        return ""
    return text[:120]


def _clean_text(value: Any, *, max_len: int = 120) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:max_len]


def _fingerprint(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"admin_{digest[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
