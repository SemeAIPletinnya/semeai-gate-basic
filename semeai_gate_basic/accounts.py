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
MIN_PASSWORD_LEN = 8
PBKDF2_ITERATIONS = 200_000


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
    """Create a pending account/workspace request with password + email verification.

    Password is stored only as PBKDF2 hash. Verification token and API keys are
    never stored in raw form. Payment is not release authority.
    """

    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    _ensure_account_dirs(root)

    email = _normalize_email(str(payload.get("email") or payload.get("work_email") or ""))
    if not EMAIL_RE.match(email):
        raise AccountError("valid email is required")

    password = str(payload.get("password") or "")
    password_confirm = payload.get("password_confirm")
    if password_confirm is not None and str(password_confirm) != password:
        raise AccountError("password confirmation does not match")
    _validate_password(password)

    if _find_workspace_by_email(root, email) is not None:
        raise AccountError("an account with this email already exists — log in instead", status_code=409)
    if _find_pending_by_email(root, email) is not None:
        raise AccountError("a registration for this email is already pending verification", status_code=409)

    company = _clean_field(payload.get("company") or payload.get("workspace_name") or "Early access workspace")
    use_case = _clean_field(payload.get("use_case") or "support")
    expected_monthly_checks = _clean_field(
        payload.get("expected_monthly_checks") or payload.get("volume") or "pilot"
    )
    notes = _clean_field(payload.get("notes") or "", max_len=2000)
    password_record = _hash_password(password)

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
        "password": password_record,
        "raw_verification_token_stored": False,
        "raw_api_key_stored": False,
        "password_collected": True,
        "payment_provider": "not_configured",
        "external_billing_calls": False,
        "source": _clean_field(payload.get("source") or DEFAULT_PUBLIC_SITE_URL),
    }

    pending_path = _pending_dir(root) / f"{registration_id}.json"
    pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_event(root, {"event_type": "registration_created", **_public_registration_event(record)})

    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL", "") or DEFAULT_PUBLIC_SITE_URL).rstrip("/")
    verification_url = f"{public_site}/register.html#verify={verification_token}"
    dashboard_verify_url = f"{public_site}/dashboard.html#verify={verification_token}"

    from .email_provider import email_provider_status, send_verification_email

    delivery = send_verification_email(
        to=email,
        verification_url=verification_url,
        registration_id=registration_id,
        company=company,
        env=values,
        account_dir=root,
    )
    provider_status = email_provider_status(env=values)
    auto = bool(provider_status.get("automatic_email_delivery")) and bool((delivery.get("user") or {}).get("ok"))
    user_delivery = delivery.get("user") or {}

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
            "delivery_provider": user_delivery.get("provider") or provider_status.get("provider") or "outbox_only",
            "manual_delivery": not auto,
            "email_sent": bool(user_delivery.get("ok") and user_delivery.get("delivery") == "sent"),
            "delivery_status": user_delivery.get("delivery"),
            "verification_url": verification_url,
            "dashboard_verification_url": dashboard_verify_url,
            "expires_at": expires_at,
            "raw_verification_token_stored": False,
        },
        "email_delivery": delivery,
        "account_storage": {
            "server_side_record_created": True,
            "password_collected": True,
            "raw_api_key_stored": False,
            "password_auth_implemented": True,
        },
        "next_step": (
            "Check your email for the verification link. After confirm, log in with email + password "
            "or use the one-time integration API key shown at verify."
            if auto
            else "Open the verification link, then log in with email + password."
        ),
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
            "password_auth_enabled": True,
            "next_step": "Log in with email + password, or use the API key shown during first verification.",
        }

    expires_at = _parse_iso(str(record.get("expires_at") or ""))
    if expires_at < datetime.now(timezone.utc):
        record["status"] = "expired"
        pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        _append_event(root, {"event_type": "registration_expired", **_public_registration_event(record)})
        raise AccountError("verification token expired", status_code=410)

    # Password must have been set at register (SaaS path). Legacy pending without password is rejected.
    password_record = record.get("password") if isinstance(record.get("password"), dict) else None
    if not password_record or not password_record.get("hash"):
        raise AccountError(
            "this registration has no password — re-register with email + password",
            status_code=400,
        )

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
        "password": password_record,
        "password_collected": True,
        "plan": plan,
        "subscription": {
            "status": "trial",
            "tier": "free",
            "plan": "free",
            "billing_provider": "not_configured",
            "external_billing_calls": False,
            "free_checks": 5,
        },
        "billing": {
            "schema_version": "0.1-billing",
            "status": "trial",
            "payment_status": "unpaid",
            "billing_provider": "manual_usdt_trc20",
            "plan": "free",
            "network": "TRC20",
            "asset": "USDT",
            "payment_address": "TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27",
            "default_amount_usdt": "25.00",
            "manual_review_required": True,
            "automatic_onchain_verification": True,
            "external_billing_calls": False,
            "private_keys_stored": False,
            "free_checks": 5,
        },
        "created_at": verified_at,
        "api_keys": [
            {
                "api_key_hash": api_key_hash,
                "api_key_fingerprint": api_key_fingerprint,
                "status": "active",
                "created_at": verified_at,
                "label": "default",
                "raw_api_key_stored": False,
            }
        ],
        "sessions": [],
        "invariants": [
            "api_key_authentication_is_not_release_authority",
            "session_authentication_is_not_release_authority",
            "subscription_metadata_is_not_gate_authority",
            "generation_is_not_release_authority",
            "payment_is_never_gate_authority",
        ],
    }

    workspace_path = _workspaces_dir(root) / f"{workspace_id}.json"
    workspace_path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")

    record["status"] = "verified"
    record["verified_at"] = verified_at
    record["workspace_id"] = workspace_id
    record["api_key_fingerprint"] = api_key_fingerprint
    # Drop password from pending file after verify (lives only on workspace).
    record.pop("password", None)
    pending_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    _append_event(
        root,
        {
            "event_type": "registration_verified",
            **_public_registration_event(record),
            "workspace_id": workspace_id,
            "api_key_fingerprint": api_key_fingerprint,
            "raw_api_key_stored": False,
            "password_auth_enabled": True,
        },
    )

    # Also mint a browser session so cabinet can open immediately after verify.
    session = _create_session(workspace_path, workspace, env=values)

    try:
        from .users import create_or_update_user_from_workspace

        # password already on workspace; re-hash is avoided by passing None if we only link
        create_or_update_user_from_workspace(
            email=str(record.get("email") or ""),
            password=None,
            workspace_id=workspace_id,
            role="owner",
            account_dir=root,
            env=values,
        )
        # ensure user has password from pending (stored only on workspace at this point)
        from .users import load_user_by_email, save_user

        found = load_user_by_email(str(record.get("email") or ""), account_dir=root, env=values)
        if found and password_record:
            upath, user = found
            if not user.get("password"):
                user["password"] = password_record
                save_user(upath, user)
    except Exception:
        pass

    return {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "status": "verified",
        "registration_id": record.get("registration_id"),
        "workspace_id": workspace_id,
        "workspace_name": workspace["workspace_name"],
        "email": workspace.get("email"),
        "api_key": api_key,
        "api_key_fingerprint": api_key_fingerprint,
        "api_key_issued": True,
        "raw_api_key_stored": False,
        "session_token": session["session_token"],
        "session_expires_at": session["expires_at"],
        "password_auth_enabled": True,
        "subscription": workspace["subscription"],
        "billing": workspace["billing"],
        "next_step": (
            "Save the integration API key if you need server-side calls. "
            "Use email + password (or the session token) for the personal cabinet."
        ),
    }


def login_with_password(
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Authenticate email + password and issue a browser session token."""

    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    _ensure_account_dirs(root)

    email = _normalize_email(str(payload.get("email") or ""))
    password = str(payload.get("password") or "")
    if not EMAIL_RE.match(email) or not password:
        raise AccountError("email and password are required", status_code=400)

    found = _find_workspace_by_email(root, email)
    if found is None:
        if _find_pending_by_email(root, email) is not None:
            raise AccountError("email not verified yet — open the confirmation link first", status_code=403)
        raise AccountError("invalid email or password", status_code=401)

    path, workspace = found
    password_record = workspace.get("password") if isinstance(workspace.get("password"), dict) else None
    if not password_record or not _verify_password(password, password_record):
        raise AccountError("invalid email or password", status_code=401)
    if workspace.get("status") != "active":
        raise AccountError("workspace is not active", status_code=403)

    session = _create_session(path, workspace, env=values)
    _append_event(
        root,
        {
            "event_type": "login_success",
            "workspace_id": workspace.get("workspace_id"),
            "email_hash": workspace.get("email_hash"),
            "session_fingerprint": session["session_fingerprint"],
        },
    )

    return {
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "api_version": ACCOUNT_API_VERSION,
        "status": "authenticated",
        "workspace_id": workspace.get("workspace_id"),
        "workspace_name": workspace.get("workspace_name"),
        "email": workspace.get("email"),
        "session_token": session["session_token"],
        "session_expires_at": session["expires_at"],
        "auth_mode": "password_session",
        "subscription": workspace.get("subscription") or {},
        "billing": workspace.get("billing") or {},
        "next_step": "Use session_token as Bearer for /v0/account, /v0/check, receipts, and billing.",
    }


def logout_session(
    session_token: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    token = str(session_token or "").strip()
    if not token:
        raise AccountError("session_token is required")

    token_hash = _hash_secret(token)
    for path in _workspaces_dir(root).glob("*.json"):
        try:
            workspace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sessions = workspace.get("sessions") if isinstance(workspace.get("sessions"), list) else []
        changed = False
        for item in sessions:
            if not isinstance(item, dict):
                continue
            if item.get("session_hash") == token_hash and item.get("status") == "active":
                item["status"] = "revoked"
                item["revoked_at"] = _now()
                changed = True
        if changed:
            workspace["sessions"] = sessions
            path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "logged_out",
                "workspace_id": workspace.get("workspace_id"),
            }
    return {"status": "logged_out", "workspace_id": None}


def authenticate_account_api_key(
    supplied_api_key: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Authenticate either integration API key or browser session token."""

    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR", "") or DEFAULT_ACCOUNT_DIR)
    if not _workspaces_dir(root).exists():
        return None

    raw = str(supplied_api_key or "").strip()
    if not raw:
        return None
    key_hash = _hash_secret(raw)
    now = datetime.now(timezone.utc)

    for path in _workspaces_dir(root).glob("*.json"):
        try:
            workspace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if workspace.get("status") != "active":
            continue

        subscription = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
        base = {
            "authenticated": True,
            "workspace_id": workspace.get("workspace_id"),
            "workspace_name": workspace.get("workspace_name"),
            "email": workspace.get("email"),
            "subscription": {
                "status": subscription.get("status") or "active",
                "tier": subscription.get("tier") or workspace.get("plan") or "developer",
                "billing_provider": subscription.get("billing_provider") or "not_configured",
                "external_billing_calls": bool(subscription.get("external_billing_calls", False)),
            },
        }

        for item in workspace.get("api_keys", []):
            if not isinstance(item, dict) or item.get("status") != "active":
                continue
            if item.get("api_key_hash") == key_hash:
                return {
                    **base,
                    "auth_mode": "issued_api_key",
                    "api_key_fingerprint": item.get("api_key_fingerprint") or _fingerprint_api_key(raw),
                }

        sessions = workspace.get("sessions") if isinstance(workspace.get("sessions"), list) else []
        dirty = False
        for item in sessions:
            if not isinstance(item, dict) or item.get("status") != "active":
                continue
            if item.get("session_hash") != key_hash:
                continue
            exp = _parse_iso(str(item.get("expires_at") or ""))
            if exp < now:
                item["status"] = "expired"
                dirty = True
                continue
            if dirty:
                workspace["sessions"] = sessions
                path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                **base,
                "auth_mode": "password_session",
                "api_key_fingerprint": item.get("session_fingerprint") or _fingerprint_api_key(raw),
                "session": True,
            }
        if dirty:
            workspace["sessions"] = sessions
            path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "password_auth_implemented": True,
        "session_auth_implemented": True,
        "email_delivery_provider": "manual_link_v0_1",
        "email_verification_required": True,
    }


def _create_session(
    workspace_path: Path,
    workspace: dict[str, Any],
    *,
    env: Mapping[str, str],
) -> dict[str, Any]:
    token = "sem_sess_" + secrets.token_urlsafe(32)
    created = _now()
    expires = _iso(_parse_iso(created) + timedelta(hours=_session_ttl_hours(env)))
    item = {
        "session_hash": _hash_secret(token),
        "session_fingerprint": _fingerprint_api_key(token),
        "status": "active",
        "created_at": created,
        "expires_at": expires,
        "raw_session_token_stored": False,
    }
    sessions = workspace.get("sessions") if isinstance(workspace.get("sessions"), list) else []
    # Cap active sessions
    active = [s for s in sessions if isinstance(s, dict) and s.get("status") == "active"]
    if len(active) >= 10:
        # revoke oldest
        active_sorted = sorted(active, key=lambda s: str(s.get("created_at") or ""))
        for old in active_sorted[: max(0, len(active_sorted) - 9)]:
            old["status"] = "revoked"
            old["revoked_at"] = created
            old["revoke_reason"] = "session_limit"
    sessions.append(item)
    workspace["sessions"] = sessions
    workspace_path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "session_token": token,
        "session_fingerprint": item["session_fingerprint"],
        "expires_at": expires,
    }


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AccountError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if password.strip() != password or not password.strip():
        raise AccountError("password cannot be empty or only whitespace")
    if password.lower() in {"password", "12345678", "qwertyui", "semeai123"}:
        raise AccountError("password is too common")


def _hash_password(password: str, *, salt: str | None = None) -> dict[str, Any]:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return {
        "algo": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt_value,
        "hash": digest.hex(),
    }


def _verify_password(password: str, stored: Mapping[str, Any]) -> bool:
    try:
        iterations = int(stored.get("iterations") or PBKDF2_ITERATIONS)
        salt = str(stored.get("salt") or "")
        expected = str(stored.get("hash") or "")
    except (TypeError, ValueError):
        return False
    if not salt or not expected:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return secrets.compare_digest(digest.hex(), expected)


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


def _find_pending_by_email(root: Path, email: str) -> dict[str, Any] | None:
    email_hash = _hash_secret(_normalize_email(email))
    for path in _pending_dir(root).glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("email_hash") == email_hash and record.get("status") == "pending_email_verification":
            return record
    return None


def _find_workspace_by_email(root: Path, email: str) -> tuple[Path, dict[str, Any]] | None:
    email_hash = _hash_secret(_normalize_email(email))
    for path in _workspaces_dir(root).glob("*.json"):
        try:
            workspace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if workspace.get("email_hash") == email_hash and workspace.get("status") == "active":
            return path, workspace
    return None


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
        "password_collected": bool(record.get("password_collected")),
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


def _session_ttl_hours(env: Mapping[str, str]) -> int:
    raw = str(env.get("SEMEAI_GATE_SESSION_TTL_HOURS", str(24 * 30)) or str(24 * 30))
    try:
        value = int(raw)
    except ValueError:
        return 24 * 30
    return max(1, min(value, 24 * 90))


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
