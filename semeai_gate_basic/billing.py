from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import secrets
from typing import Any, Mapping


BILLING_SCHEMA_VERSION = "0.1-billing"
DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"
DEFAULT_USDT_TRC20_ADDRESS = "TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27"
TRON_TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class BillingError(ValueError):
    """Raised when manual billing metadata cannot be created safely."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def billing_status(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return browser-safe manual billing metadata for an issued workspace key."""

    root = _account_root(account_dir=account_dir, env=env)
    workspace_path, workspace = _load_workspace(root, auth)
    billing = _default_billing_record(auth)
    if workspace_path is not None and workspace is not None:
        billing.update(_public_billing_summary(workspace.get("billing")))
    return {
        "schema_version": BILLING_SCHEMA_VERSION,
        "billing": billing,
        "manual_crypto": _manual_crypto_config(env=env),
        "private_keys_stored": False,
        "automatic_onchain_verification": False,
        "payment_metadata_is_not_gate_authority": True,
    }


def create_manual_crypto_intent(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Create a manual USDT/TRC20 payment intent.

    This does not verify a blockchain transfer and does not activate a workspace.
    It only records a reviewable payment intent for early paid pilots.
    """

    _require_workspace_auth(auth)
    root = _account_root(account_dir=account_dir, env=env)
    _ensure_billing_dirs(root)
    workspace_path, workspace = _load_workspace(root, auth)
    if workspace_path is None or workspace is None:
        raise BillingError("workspace record not found", status_code=404)

    values = env or os.environ
    request = payload or {}
    crypto = _manual_crypto_config(env=env)
    plan = _clean_field(request.get("plan") or values.get("SEMEAI_GATE_MANUAL_BILLING_PLAN") or "pilot")
    amount_usdt = _normalize_amount(request.get("amount_usdt") or values.get("SEMEAI_GATE_MANUAL_USDT_AMOUNT") or "25.00")
    invoice_id = "inv_" + secrets.token_hex(8)
    created_at = _now()
    due_at = None
    address = crypto["payment_address"]
    review_email = crypto.get("feedback_email")

    intent = {
        "schema_version": BILLING_SCHEMA_VERSION,
        "invoice_id": invoice_id,
        "workspace_id": auth.get("workspace_id"),
        "workspace_name": auth.get("workspace_name"),
        "api_key_fingerprint": auth.get("api_key_fingerprint"),
        "billing_provider": "manual_usdt_trc20",
        "network": "TRC20",
        "asset": "USDT",
        "amount_usdt": amount_usdt,
        "plan": plan,
        "payment_address": address,
        "payment_status": "pending_payment",
        "billing_status": "pending_payment",
        "activation_mode": "manual_review",
        "automatic_onchain_verification": False,
        "external_billing_calls": False,
        "private_keys_stored": False,
        "audit_preserved": True,
        "created_at": created_at,
        "due_at": due_at,
        "next_step": (
            "Send USDT on TRC20, submit the transaction id for manual review, then email "
            f"{review_email} with workspace_id + invoice_id + txid."
        ),
        "review_email": review_email,
        "invariants": _billing_invariants(),
    }

    _write_invoice(root, intent)
    _update_workspace_billing(
        workspace_path,
        workspace,
        {
            "status": "pending_payment",
            "payment_status": "pending_payment",
            "billing_provider": "manual_usdt_trc20",
            "plan": plan,
            "latest_invoice_id": invoice_id,
            "latest_invoice_created_at": created_at,
            "latest_amount_usdt": amount_usdt,
            "network": "TRC20",
            "asset": "USDT",
            "payment_address": address,
            "automatic_onchain_verification": False,
            "external_billing_calls": False,
            "private_keys_stored": False,
        },
    )
    _append_billing_event(root, {"event_type": "manual_crypto_intent_created", **_event_projection(intent)})
    return {
        "schema_version": BILLING_SCHEMA_VERSION,
        "status": "created",
        "invoice": intent,
        "billing": _public_billing_summary({"latest_invoice_id": invoice_id, **intent}),
    }


def submit_manual_crypto_txid(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Attach a TRC20 transaction id to a manual invoice for operator review."""

    _require_workspace_auth(auth)
    root = _account_root(account_dir=account_dir, env=env)
    _ensure_billing_dirs(root)
    workspace_path, workspace = _load_workspace(root, auth)
    if workspace_path is None or workspace is None:
        raise BillingError("workspace record not found", status_code=404)

    invoice_id = _clean_field(payload.get("invoice_id") or "")
    txid = str(payload.get("txid") or payload.get("transaction_id") or "").strip()
    if not invoice_id:
        raise BillingError("invoice_id is required")
    if not TRON_TXID_RE.match(txid):
        raise BillingError("txid must be a 64-character hexadecimal TRC20 transaction id")

    invoice = _read_invoice(root, invoice_id)
    if invoice is None:
        raise BillingError("invoice not found", status_code=404)
    if invoice.get("workspace_id") != auth.get("workspace_id"):
        raise BillingError("invoice does not belong to this workspace", status_code=403)

    submitted_at = _now()
    txid_hash = _hash(txid)
    crypto_cfg = _manual_crypto_config(env=env)
    onchain: dict[str, Any] = {}
    try:
        from .crypto_verify import verify_usdt_trc20_txid

        onchain = verify_usdt_trc20_txid(
            txid,
            expected_to=str(crypto_cfg.get("payment_address") or DEFAULT_USDT_TRC20_ADDRESS),
            expected_amount_usdt=invoice.get("amount_usdt") or crypto_cfg.get("default_amount_usdt"),
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        onchain = {
            "verification_status": "unavailable",
            "ok": False,
            "error": str(exc),
            "automatic_onchain_verification": False,
        }

    proof = {
        "schema_version": BILLING_SCHEMA_VERSION,
        "invoice_id": invoice_id,
        "workspace_id": auth.get("workspace_id"),
        "api_key_fingerprint": auth.get("api_key_fingerprint"),
        "payment_status": "pending_review",
        "billing_status": "pending_review",
        "txid": txid,
        "txid_hash": txid_hash,
        "raw_txid_stored": True,
        "manual_review_required": True,
        "automatic_onchain_verification": bool(onchain.get("automatic_onchain_verification")),
        "onchain": onchain,
        "external_billing_calls": bool(onchain.get("provider") == "trongrid"),
        "audit_preserved": True,
        "submitted_at": submitted_at,
        "operator_note": _clean_field(payload.get("operator_note") or payload.get("note") or "", max_len=500),
        "next_step": "Operator must verify the transaction on-chain before activating paid access.",
        "invariants": _billing_invariants(),
    }

    invoice.update(
        {
            "payment_status": "pending_review",
            "billing_status": "pending_review",
            "submitted_txid_hash": txid_hash,
            "raw_txid_stored": True,
            "manual_review_required": True,
            "submitted_at": submitted_at,
            "onchain_verification_status": onchain.get("verification_status"),
        }
    )
    _write_invoice(root, invoice)
    _write_payment_proof(root, proof)
    _update_workspace_billing(
        workspace_path,
        workspace,
        {
            "status": "pending_review",
            "payment_status": "pending_review",
            "billing_provider": "manual_usdt_trc20",
            "latest_invoice_id": invoice_id,
            "latest_txid_hash": txid_hash,
            "latest_txid_submitted_at": submitted_at,
            "manual_review_required": True,
            "automatic_onchain_verification": bool(onchain.get("automatic_onchain_verification")),
            "onchain_verification_status": onchain.get("verification_status"),
            "external_billing_calls": bool(onchain.get("provider") == "trongrid"),
            "private_keys_stored": False,
        },
    )
    _append_billing_event(root, {"event_type": "manual_crypto_txid_submitted", **_event_projection(proof)})
    review_email = crypto_cfg.get("feedback_email")
    email_result: dict[str, Any] = {}
    try:
        from .email_provider import send_billing_review_email

        email_result = send_billing_review_email(
            workspace_id=str(auth.get("workspace_id") or ""),
            invoice_id=invoice_id,
            txid=txid,
            workspace_name=str(auth.get("workspace_name") or workspace.get("workspace_name") or ""),
            env=env,
            account_dir=root,
        )
    except Exception as exc:  # noqa: BLE001
        email_result = {"ok": False, "error": str(exc)}
    return {
        "schema_version": BILLING_SCHEMA_VERSION,
        "status": "pending_review",
        "payment_status": "pending_review",
        "billing_status": "pending_review",
        "invoice_id": invoice_id,
        "txid_hash": txid_hash,
        "manual_review_required": True,
        "automatic_onchain_verification": bool(onchain.get("automatic_onchain_verification")),
        "onchain": onchain,
        "audit_preserved": True,
        "next_step": (
            "Do not assume paid activation until the operator verifies this transaction. "
            f"Email {review_email} with workspace_id, invoice_id, and txid for faster pilot review."
        ),
        "review_email": review_email,
        "operator_notice": email_result,
    }


def _manual_crypto_config(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    operator_email = str(
        values.get("SEMEAI_GATE_OPERATOR_EMAIL")
        or values.get("SEMEAI_GATE_FEEDBACK_EMAIL")
        or "adelayida0403@gmail.com"
    ).strip()
    feedback_email = str(values.get("SEMEAI_GATE_FEEDBACK_EMAIL") or operator_email).strip()
    return {
        "billing_provider": "manual_usdt_trc20",
        "network": "TRC20",
        "asset": "USDT",
        "payment_address": str(values.get("SEMEAI_GATE_USDT_TRC20_ADDRESS") or DEFAULT_USDT_TRC20_ADDRESS).strip(),
        "default_amount_usdt": _normalize_amount(values.get("SEMEAI_GATE_MANUAL_USDT_AMOUNT") or "25.00"),
        "automatic_onchain_verification": False,
        "external_billing_calls": False,
        "private_keys_stored": False,
        "manual_review_required": True,
        "stripe_enabled": False,
        "operator_email": operator_email,
        "feedback_email": feedback_email,
        "review_instructions": (
            f"After submitting TXID, email {feedback_email} with workspace_id, invoice_id, "
            "and the TRC20 transaction hash for manual pilot activation review."
        ),
    }


def _require_workspace_auth(auth: Mapping[str, Any]) -> None:
    if not auth.get("workspace_id"):
        raise BillingError("manual billing requires an issued workspace API key", status_code=403)


def _account_root(*, account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return Path(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)


def _ensure_billing_dirs(root: Path) -> None:
    (root / "billing_intents").mkdir(parents=True, exist_ok=True)
    (root / "billing_proofs").mkdir(parents=True, exist_ok=True)


def _load_workspace(root: Path, auth: Mapping[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    workspace_id = str(auth.get("workspace_id") or "").strip()
    if not workspace_id:
        return None, None
    path = root / "workspaces" / f"{workspace_id}.json"
    if not path.exists():
        return None, None
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BillingError(f"workspace record could not be read: {exc}", status_code=500) from exc


def _write_invoice(root: Path, invoice: Mapping[str, Any]) -> None:
    invoice_id = str(invoice.get("invoice_id") or "")
    if not invoice_id:
        raise BillingError("invoice_id missing", status_code=500)
    path = root / "billing_intents" / f"{invoice_id}.json"
    path.write_text(json.dumps(dict(invoice), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_invoice(root: Path, invoice_id: str) -> dict[str, Any] | None:
    path = root / "billing_intents" / f"{invoice_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BillingError(f"invoice could not be read: {exc}", status_code=500) from exc


def _write_payment_proof(root: Path, proof: Mapping[str, Any]) -> None:
    invoice_id = str(proof.get("invoice_id") or "")
    txid_hash = str(proof.get("txid_hash") or "")
    path = root / "billing_proofs" / f"{invoice_id}_{txid_hash[:12]}.json"
    path.write_text(json.dumps(dict(proof), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _update_workspace_billing(workspace_path: Path, workspace: dict[str, Any], billing_patch: Mapping[str, Any]) -> None:
    existing = workspace.get("billing") if isinstance(workspace.get("billing"), dict) else {}
    workspace["billing"] = {
        "schema_version": BILLING_SCHEMA_VERSION,
        "updated_at": _now(),
        **existing,
        **dict(billing_patch),
    }
    subscription = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
    subscription["billing_provider"] = workspace["billing"].get("billing_provider") or subscription.get("billing_provider")
    subscription["external_billing_calls"] = False
    workspace["subscription"] = subscription
    workspace_path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_billing_event(root: Path, event: Mapping[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": _now(), **dict(event)}
    with (root / "billing_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _public_billing_summary(value: Any) -> dict[str, Any]:
    billing = value if isinstance(value, dict) else {}
    return {
        "status": billing.get("status") or billing.get("billing_status") or "trial",
        "payment_status": billing.get("payment_status") or "unpaid",
        "billing_provider": billing.get("billing_provider") or "manual_usdt_trc20",
        "plan": billing.get("plan") or "developer",
        "latest_invoice_id": billing.get("latest_invoice_id"),
        "latest_amount_usdt": billing.get("latest_amount_usdt") or billing.get("amount_usdt"),
        "network": billing.get("network") or "TRC20",
        "asset": billing.get("asset") or "USDT",
        "manual_review_required": bool(billing.get("manual_review_required", True)),
        "automatic_onchain_verification": False,
        "external_billing_calls": False,
        "private_keys_stored": False,
    }


def _default_billing_record(auth: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "trial",
        "payment_status": "unpaid",
        "billing_provider": "manual_usdt_trc20",
        "workspace_id": auth.get("workspace_id"),
        "manual_review_required": True,
        "automatic_onchain_verification": False,
        "external_billing_calls": False,
        "private_keys_stored": False,
    }


def _event_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record.get("schema_version"),
        "invoice_id": record.get("invoice_id"),
        "workspace_id": record.get("workspace_id"),
        "api_key_fingerprint": record.get("api_key_fingerprint"),
        "billing_provider": record.get("billing_provider"),
        "payment_status": record.get("payment_status"),
        "billing_status": record.get("billing_status"),
        "txid_hash": record.get("txid_hash") or record.get("submitted_txid_hash"),
        "audit_preserved": True,
        "automatic_onchain_verification": False,
    }


def _normalize_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value or "0").strip())
    except (InvalidOperation, ValueError) as exc:
        raise BillingError("amount_usdt must be numeric") from exc
    if amount <= 0:
        raise BillingError("amount_usdt must be positive")
    if amount > Decimal("100000"):
        raise BillingError("amount_usdt is outside v0.1 manual billing bounds")
    return format(amount.quantize(Decimal("0.01")), "f")


def _clean_field(value: Any, *, max_len: int = 120) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split())
    return text[:max_len]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _billing_invariants() -> list[str]:
    return [
        "payment_metadata_is_not_gate_authority",
        "subscription_metadata_is_not_release_authority",
        "manual_txid_submission_is_not_payment_verification",
        "private_keys_are_not_stored",
        "generation_is_not_release_authority",
        "silence_means_release_denied_execution_withheld_audit_preserved",
    ]
