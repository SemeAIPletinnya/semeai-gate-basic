"""User identity layer for multi-workspace SaaS (password + OAuth)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
from typing import Any, Mapping

from .accounts import (
    AccountError,
    _hash_password,
    _hash_secret,
    _normalize_email,
    _validate_password,
    _verify_password,
    _now,
    _iso,
    _parse_iso,
    _clean_field,
    DEFAULT_ACCOUNT_DIR,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _root(account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return Path(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)


def _users_dir(root: Path) -> Path:
    return root / "users"


def _user_path(root: Path, email: str) -> Path:
    return _users_dir(root) / f"user_{_hash_secret(_normalize_email(email))[:24]}.json"


def ensure_user_dirs(root: Path) -> None:
    _users_dir(root).mkdir(parents=True, exist_ok=True)
    (root / "password_resets").mkdir(parents=True, exist_ok=True)
    (root / "invites").mkdir(parents=True, exist_ok=True)


def load_user_by_email(
    email: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    root = _root(account_dir, env)
    path = _user_path(root, email)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return path, data


def save_user(path: Path, user: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(user), ensure_ascii=False, indent=2), encoding="utf-8")


def create_or_update_user_from_workspace(
    *,
    email: str,
    password: str | None,
    workspace_id: str,
    role: str = "owner",
    name: str = "",
    oauth: Mapping[str, Any] | None = None,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = _root(account_dir, env)
    ensure_user_dirs(root)
    email_n = _normalize_email(email)
    if not EMAIL_RE.match(email_n):
        raise AccountError("valid email is required")

    existing = load_user_by_email(email_n, account_dir=root, env=env)
    now = _now()
    if existing is None:
        user_id = "usr_" + secrets.token_hex(8)
        user: dict[str, Any] = {
            "schema_version": "0.2-user",
            "user_id": user_id,
            "email": email_n,
            "email_hash": _hash_secret(email_n),
            "name": _clean_field(name or email_n.split("@")[0]),
            "created_at": now,
            "password": _hash_password(password) if password else None,
            "oauth": dict(oauth or {}),
            "memberships": [
                {"workspace_id": workspace_id, "role": role, "status": "active", "joined_at": now}
            ],
            "default_workspace_id": workspace_id,
        }
        path = _user_path(root, email_n)
        save_user(path, user)
        return user

    path, user = existing
    if password:
        user["password"] = _hash_password(password)
    if oauth:
        o = user.get("oauth") if isinstance(user.get("oauth"), dict) else {}
        o.update(dict(oauth))
        user["oauth"] = o
    memberships = user.get("memberships") if isinstance(user.get("memberships"), list) else []
    if not any(m.get("workspace_id") == workspace_id for m in memberships if isinstance(m, dict)):
        memberships.append(
            {"workspace_id": workspace_id, "role": role, "status": "active", "joined_at": now}
        )
    user["memberships"] = memberships
    if not user.get("default_workspace_id"):
        user["default_workspace_id"] = workspace_id
    user["updated_at"] = now
    save_user(path, user)
    return user


def authenticate_user_password(
    email: str,
    password: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    found = load_user_by_email(email, account_dir=account_dir, env=env)
    if found is None:
        raise AccountError("invalid email or password", status_code=401)
    _, user = found
    pwd = user.get("password") if isinstance(user.get("password"), dict) else None
    if not pwd or not _verify_password(password, pwd):
        raise AccountError("invalid email or password", status_code=401)
    return user


def request_password_reset(
    email: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Always returns generic success; issues token only if user exists."""

    values = env or os.environ
    root = _root(account_dir, values)
    ensure_user_dirs(root)
    email_n = _normalize_email(email)
    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL") or "https://semeai.tech").rstrip("/")
    generic = {
        "status": "ok",
        "message": "If an account exists for that email, a reset link was sent.",
    }
    found = load_user_by_email(email_n, account_dir=root, env=values)
    if found is None:
        # also allow workspace-only legacy accounts
        from .accounts import _find_workspace_by_email

        ws = _find_workspace_by_email(root, email_n)
        if ws is None:
            return generic

    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    record = {
        "email": email_n,
        "email_hash": _hash_secret(email_n),
        "token_hash": _hash_secret(token),
        "created_at": _now(),
        "expires_at": _iso(datetime.now(timezone.utc) + timedelta(hours=2)),
        "used": False,
    }
    path = root / "password_resets" / f"reset_{secrets.token_hex(8)}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    reset_url = f"{public_site}/reset.html#token={token}"

    try:
        from .email_provider import send_email

        send_email(
            to=email_n,
            subject="Reset your SemeAI Gate password",
            text=(
                f"Reset your password:\n\n{reset_url}\n\n"
                "This link expires in 2 hours. If you did not request it, ignore this email."
            ),
            html=(
                f"<p>Reset your SemeAI Gate password:</p>"
                f'<p><a href="{reset_url}">Reset password</a></p>'
                f"<p>This link expires in 2 hours.</p>"
            ),
            tags=["password_reset"],
            env=values,
            account_dir=root,
        )
    except Exception:
        pass

    out = dict(generic)
    # Always include token in test/local when account dir is temp or expose flag set
    if str(values.get("SEMEAI_GATE_EXPOSE_RESET_URL", "")).lower() in {"1", "true", "yes"}:
        out["reset_url"] = reset_url
        out["reset_token"] = token
    return out


def reset_password_with_token(
    token: str,
    password: str,
    password_confirm: str | None = None,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = _root(account_dir, env)
    ensure_user_dirs(root)
    if password_confirm is not None and password_confirm != password:
        raise AccountError("password confirmation does not match")
    _validate_password(password)
    token = str(token or "").strip()
    if not token:
        raise AccountError("reset token is required")
    token_hash = _hash_secret(token)

    match_path = None
    match_rec = None
    for path in (root / "password_resets").glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("token_hash") == token_hash:
            match_path, match_rec = path, rec
            break
    if match_rec is None or match_path is None:
        raise AccountError("invalid or expired reset token", status_code=404)
    if match_rec.get("used"):
        raise AccountError("reset token already used", status_code=410)
    if _parse_iso(str(match_rec.get("expires_at") or "")) < datetime.now(timezone.utc):
        raise AccountError("reset token expired", status_code=410)

    email = str(match_rec.get("email") or "")
    found = load_user_by_email(email, account_dir=root, env=env)
    pwd_record = _hash_password(password)
    if found is None:
        # migrate legacy workspace-only account into user
        from .accounts import _find_workspace_by_email

        ws = _find_workspace_by_email(root, email)
        if ws is None:
            raise AccountError("account not found", status_code=404)
        _, workspace = ws
        create_or_update_user_from_workspace(
            email=email,
            password=password,
            workspace_id=str(workspace.get("workspace_id")),
            role="owner",
            account_dir=root,
            env=env,
        )
        # also update workspace password
        workspace["password"] = pwd_record
        ws[0].write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path, user = found
        user["password"] = pwd_record
        user["updated_at"] = _now()
        save_user(path, user)
        # sync primary workspace password if present
        from .accounts import _find_workspace_by_email

        ws = _find_workspace_by_email(root, email)
        if ws is not None:
            wpath, workspace = ws
            workspace["password"] = pwd_record
            wpath.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")

    match_rec["used"] = True
    match_rec["used_at"] = _now()
    match_path.write_text(json.dumps(match_rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "password_updated", "email": email, "next_step": "Log in with your new password."}


def find_user_by_oauth(
    provider: str,
    subject: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    root = _root(account_dir, env)
    ensure_user_dirs(root)
    for path in _users_dir(root).glob("user_*.json"):
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        oauth = user.get("oauth") if isinstance(user.get("oauth"), dict) else {}
        if str(oauth.get(provider)) == str(subject):
            return user
    return None
