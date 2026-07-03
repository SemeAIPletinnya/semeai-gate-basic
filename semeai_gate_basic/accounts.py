from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
from typing import Any, Mapping

ACCOUNT_API_VERSION = "0.1"
ACCOUNT_SCHEMA_VERSION = "0.1-account"
DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"
DEFAULT_PUBLIC_SITE_URL = "https://semeai.tech"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """Raised when account registration or verification cannot proceed."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def register_workspace(
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Create a pending account/workspace request.

    This is a deterministic local account primitive, not payment processing and
    not release authority. The verification token is stored only as a hash.
    """

    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    _ensure_account_dirs(root)

    email = _normalize_email(str(payload.get("email") or payload.get("work_email") or ""))
    if not EMAIL_RE.match(email):
        raise AccountError("valid email is required")

    company = _clean_field(payload.get("company") or payload.get("workspace_name") or "Early access workspace")
    use_case = _clean_field(payload.get("use_case") or "support")
    expected_monthly_checks = _clean_field(
        payload.get("expected_monthly_checks") or payload.get("volume") or "pilot"
    )
    notes = _clean_field(payload.get("notes") or "", max_len=2000)

    created_at = _now()
    expires_at = _iso(_parse_iso(created_at) + timedelta(hours=_verification_ttl_hours(values)))
    registration_id = "reg_" + secrets.token_hex(8)
    verification_token = secrets.token_urlsafe(32)
    token_hash = _hash_secret(verification_token)

    record = {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "registration_id": registration_id,
        "status": "pending_email_verification",
        "email": email,
        "email_hash": _hash_secret(email),
        "company": company,
        "use_case": use_case,
        "expected_monthly_checks": expected_monthly_checks,
        "notes": notes,
        "requested_plan": _clean_field(payload.get("requested_plan") or "developer"),
        "created_at": created_at,
        "expires_at": expires_at,
        "verification_token_hash": token_hash,
        "raw_verification_token_stored": False,
        "raw_api_key_stored": False,
        "password_collected": False,
        "payment_provider": "not_configured",
        "external_billing_calls": False,
        "source": _clean_field(payload.get("source") or DEFAULT_PUBLIC_SITE_URL),
    }

    pending_path = _pending_dir(root) / f"{registration_id}.json"
    pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_event(root, {"event_type": "registration_created", **_public_registration_event(record)})

    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL", "") or DEFAULT_PUBLIC_SITE_URL).rstrip("/")
    verification_url = f"{public_site}/#verify={verification_token}"

    return {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "status": "verification_required",
        "registration_id": registration_id,
        "workspace_status": "pending_email_verification",
        "email": email,
        "company": company,
        "verification": {
            "method": "email_link",
            "delivery_provider": "not_configured",
            "manual_delivery": True,
            "verification_url": verification_url,
            "expires_at": expires_at,
            "raw_verification_token_stored": False,
        },
        "account_storage": {
            "server_side_record_created": True,
            "password_collected": False,
            "raw_api_key_stored": False,
        },
        "next_step": "Open the verification link to issue the workspace API key.",
    }


def verify_registration(
    verification_token: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify a pending registration and issue one API key."""

    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    _ensure_account_dirs(root)

    token = str(verification_token or "").strip()
    if not token:
        raise AccountError("verification_token is required")
    token_hash = _hash_secret(token)
    pending_path, record = _find_pending_by_token_hash(root, token_hash)
    if record is None or pending_path is None:
        raise AccountError("invalid verification token", status_code=404)

    if record.get("status") == "verified":
        return {
            "schema_version": ACCOUNT_SCHEMA_VERSION,
            "api_version": ACCOUNT_API_VERSION,
            "status": "already_verified",
            "registration_id": record.get("registration_id"),
            "workspace_id": record.get("workspace_id"),
            "api_key_issued": False,
            "raw_api_key_stored": False,
            "next_step": "Use the API key that was shown during first verification.",
        }

    expires_at = _parse_iso(str(record.get("expires_at") or ""))
    if expires_at < datetime.now(timezone.utc):
        record["status"] = "expired"
        pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        _append_event(root, {"event_type": "registration_expired", **_public_registration_event(record)})
        raise AccountError("verification token expired", status_code=410)

    workspace_id = "ws_" + secrets.token_hex(8)
    api_key = "sem_live_" + secrets.token_urlsafe(32)
    api_key_hash = _hash_secret(api_key)
    api_key_fingerprint = _fingerprint_api_key(api_key)
    verified_at = _now()
    plan = str(record.get("requested_plan") or "developer")

    workspace = {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "workspace_id": workspace_id,
        "registration_id": record.get("registration_id"),
        "status": "active",
        "workspace_name": record.get("company") or "SemeAI Gate workspace",
        "email": record.get("email"),
        "email_hash": record.get("email_hash"),
        "plan": plan,
        "subscription": {
            "status": "active",
            "tier": plan,
            "billing_provider": "not_configured",
            "external_billing_calls": False,
        },
        "billing": {
            "schema_version": "0.1-billing",
            "status": "trial",
            "payment_status": "unpaid",
            "billing_provider": "manual_usdt_trc20",
            "network": "TRC20",
            "asset": "USDT",
            "manual_review_required": True,
            "automatic_onchain_verification": False,
            "external_billing_calls": False,
            "private_keys_stored": False,
        },
        "created_at": verified_at,
        "api_keys": [
            {
                "api_key_hash": api_key_hash,
                "api_key_fingerprint": api_key_fingerprint,
                "status": "active",
                "created_at": verified_at,
                "raw_api_key_stored": False,
            }
        ],
        "invariants": [
            "api_key_authentication_is_not_release_authority",
            "subscription_metadata_is_not_gate_authority",
            "generation_is_not_release_authority",
        ],
    }

    workspace_path = _workspaces_dir(root) / f"{workspace_id}.json"
    workspace_path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")

    record["status"] = "verified"
    record["verified_at"] = verified_at
    record["workspace_id"] = workspace_id
    record["api_key_fingerprint"] = api_key_fingerprint
    pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    _append_event(
        root,
        {
            "event_type": "registration_verified",
            **_public_registration_event(record),
            "workspace_id": workspace_id,
            "api_key_fingerprint": api_key_fingerprint,
            "raw_api_key_stored": False,
        },
    )

    return {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "status": "verified",
        "registration_id": record.get("registration_id"),
        "workspace_id": workspace_id,
        "workspace_name": workspace["workspace_name"],
        "api_key": api_key,
        "api_key_fingerprint": api_key_fingerprint,
        "api_key_issued": True,
        "raw_api_key_stored": False,
        "subscription": workspace["subscription"],
        "billing": workspace["billing"],
        "next_step": "Use this API key as a Bearer token for POST /v0/check. It is shown once.",
    }


def authenticate_account_api_key(
    supplied_api_key: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    if not _workspaces_dir(root).exists():
        return None

    key_hash = _hash_secret(str(supplied_api_key or "").strip())
    for path in _workspaces_dir(root).glob("*.json"):
        try:
            workspace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if workspace.get("status") != "active":
            continue
        for item in workspace.get("api_keys", []):
            if not isinstance(item, dict) or item.get("status") != "active":
                continue
            if item.get("api_key_hash") == key_hash:
                subscription = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
                return {
                    "authenticated": True,
                    "auth_mode": "issued_api_key",
                    "api_key_fingerprint": item.get("api_key_fingerprint") or _fingerprint_api_key(supplied_api_key),
                    "workspace_id": workspace.get("workspace_id"),
                    "workspace_name": workspace.get("workspace_name"),
                    "subscription": {
                        "status": subscription.get("status") or "active",
                        "tier": subscription.get("tier") or workspace.get("plan") or "developer",
                        "billing_provider": subscription.get("billing_provider") or "not_configured",
                        "external_billing_calls": bool(subscription.get("external_billing_calls", False)),
                    },
                }
    return None


def account_dir_status(
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    return {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "account_dir": str(root),
        "pending_count": _count_json(_pending_dir(root)),
        "workspace_count": _count_json(_workspaces_dir(root)),
        "raw_api_key_stored": False,
        "password_auth_implemented": False,
        "email_delivery_provider": "not_configured",
    }


def _ensure_account_dirs(root: Path) -> None:
    _pending_dir(root).mkdir(parents=True, exist_ok=True)
    _workspaces_dir(root).mkdir(parents=True, exist_ok=True)


def _pending_dir(root: Path) -> Path:
    return root / "pending"


def _workspaces_dir(root: Path) -> Path:
    return root / "workspaces"


def _account_root(value: str | Path) -> Path:
    return Path(value)


def _append_event(root: Path, event: Mapping[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": _now(), **dict(event)}
    with (root / "account_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _find_pending_by_token_hash(root: Path, token_hash: str) -> tuple[Path | None, dict[str, Any] | None]:
    for path in _pending_dir(root).glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("verification_token_hash") == token_hash:
            return path, record
    return None, None


def _public_registration_event(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "registration_id": record.get("registration_id"),
        "status": record.get("status"),
        "email_hash": record.get("email_hash"),
        "company": record.get("company"),
        "use_case": record.get("use_case"),
        "expected_monthly_checks": record.get("expected_monthly_checks"),
        "raw_verification_token_stored": False,
        "raw_api_key_stored": False,
    }


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _clean_field(value: Any, *, max_len: int = 240) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split())
    return text[:max_len]


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint_api_key(value: str) -> str:
    return _hash_secret(value)[:12]


def _verification_ttl_hours(env: Mapping[str, str]) -> int:
    raw = str(env.get("SEMEAI_GATE_VERIFICATION_TTL_HOURS", "72") or "72")
    try:
        value = int(raw)
    except ValueError:
        return 72
    return max(1, min(value, 24 * 14))


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AccountError("invalid account timestamp", status_code=500) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _count_json(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.glob("*.json"))
