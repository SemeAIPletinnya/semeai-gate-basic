"""Multi-user workspaces: invites, roles, seats."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
from typing import Any, Mapping

from .accounts import (
    AccountError,
    DEFAULT_ACCOUNT_DIR,
    _clean_field,
    _hash_secret,
    _normalize_email,
    _now,
    _iso,
    _parse_iso,
    _workspaces_dir,
    _account_root,
)
from .plans import get_plan
from .users import create_or_update_user_from_workspace, load_user_by_email


ROLES = ("owner", "admin", "member", "viewer")


def _root(account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)


def _load_workspace(root: Path, workspace_id: str) -> tuple[Path, dict[str, Any]]:
    path = _workspaces_dir(root) / f"{workspace_id}.json"
    if not path.exists():
        raise AccountError("workspace not found", status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountError(f"workspace unreadable: {exc}", status_code=500) from exc
    return path, data


def _ensure_members(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    members = workspace.get("members")
    if isinstance(members, list) and members:
        return [m for m in members if isinstance(m, dict)]
    # bootstrap owner from workspace email
    email = str(workspace.get("email") or "")
    owner = {
        "email": email,
        "email_hash": workspace.get("email_hash") or _hash_secret(_normalize_email(email)),
        "role": "owner",
        "status": "active",
        "joined_at": workspace.get("created_at") or _now(),
    }
    workspace["members"] = [owner]
    return [owner]


def _seat_limit(workspace: Mapping[str, Any]) -> int:
    plan_id = str(
        (workspace.get("subscription") or {}).get("plan")
        or (workspace.get("billing") or {}).get("plan")
        or workspace.get("plan")
        or "free"
    ).lower()
    # map legacy tiers
    alias = {
        "developer": "growth",
        "pilot": "starter",
        "enterprise_review": "scale",
    }
    plan = get_plan(alias.get(plan_id, plan_id)) or get_plan("free") or {}
    return int(plan.get("seats") or 1)


def _require_role(auth: Mapping[str, Any], workspace: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    members = _ensure_members(dict(workspace))
    email = str(auth.get("email") or "").lower()
    me = None
    for m in members:
        if str(m.get("email") or "").lower() == email and m.get("status") == "active":
            me = m
            break
    if me is None and auth.get("auth_mode") in {"issued_api_key", "password_session"}:
        # owner key fallback
        if str(workspace.get("email") or "").lower() == email or not email:
            me = {"email": workspace.get("email"), "role": "owner", "status": "active"}
    if me is None:
        raise AccountError("not a workspace member", status_code=403)
    if str(me.get("role") or "member") not in allowed:
        raise AccountError("insufficient role", status_code=403)
    return me


def get_team(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    workspace_id = str(auth.get("workspace_id") or "")
    if not workspace_id:
        raise AccountError("workspace auth required", status_code=403)
    root = _root(account_dir, env)
    path, workspace = _load_workspace(root, workspace_id)
    members = _ensure_members(workspace)
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    public_members = [
        {
            "email": m.get("email"),
            "role": m.get("role"),
            "status": m.get("status"),
            "joined_at": m.get("joined_at"),
            "invited_at": m.get("invited_at"),
        }
        for m in members
    ]
    return {
        "schema_version": "0.2-team",
        "workspace_id": workspace_id,
        "workspace_name": workspace.get("workspace_name"),
        "seats": {
            "used": sum(1 for m in members if m.get("status") in {"active", "invited"}),
            "limit": _seat_limit(workspace),
        },
        "members": public_members,
        "roles": list(ROLES),
    }


def invite_member(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    workspace_id = str(auth.get("workspace_id") or "")
    if not workspace_id:
        raise AccountError("workspace auth required", status_code=403)
    root = _root(account_dir, values)
    path, workspace = _load_workspace(root, workspace_id)
    _require_role(auth, workspace, {"owner", "admin"})
    members = _ensure_members(workspace)

    email = _normalize_email(str(payload.get("email") or ""))
    if "@" not in email:
        raise AccountError("valid email is required")
    role = str(payload.get("role") or "member").lower()
    if role not in ROLES or role == "owner":
        raise AccountError("role must be admin, member, or viewer")

    used = sum(1 for m in members if m.get("status") in {"active", "invited"})
    if used >= _seat_limit(workspace):
        raise AccountError("seat limit reached for current plan — upgrade to invite more", status_code=402)

    for m in members:
        if str(m.get("email") or "").lower() == email and m.get("status") in {"active", "invited"}:
            raise AccountError("user already invited or a member", status_code=409)

    token = secrets.token_urlsafe(24)
    invite = {
        "email": email,
        "email_hash": _hash_secret(email),
        "role": role,
        "status": "invited",
        "invited_at": _now(),
        "invited_by": auth.get("email"),
        "invite_token_hash": _hash_secret(token),
        "expires_at": _iso(datetime.now(timezone.utc) + timedelta(days=7)),
    }
    members.append(invite)
    workspace["members"] = members
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")

    # durable invite file for lookup
    (root / "invites").mkdir(parents=True, exist_ok=True)
    inv_path = root / "invites" / f"inv_{secrets.token_hex(8)}.json"
    inv_path.write_text(
        json.dumps(
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace.get("workspace_name"),
                "email": email,
                "role": role,
                "token_hash": _hash_secret(token),
                "expires_at": invite["expires_at"],
                "status": "pending",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL") or "https://semeai.tech").rstrip("/")
    invite_url = f"{public_site}/invite.html#token={token}"
    try:
        from .email_provider import send_email

        send_email(
            to=email,
            subject=f"You're invited to {workspace.get('workspace_name') or 'SemeAI Gate'}",
            text=(
                f"You were invited as {role} to workspace {workspace.get('workspace_name')}.\n\n"
                f"Accept: {invite_url}\n\nExpires in 7 days."
            ),
            html=(
                f"<p>You were invited as <strong>{role}</strong> to "
                f"<strong>{workspace.get('workspace_name')}</strong>.</p>"
                f'<p><a href="{invite_url}">Accept invite</a></p>'
            ),
            tags=["team_invite"],
            env=values,
            account_dir=root,
        )
    except Exception:
        pass

    result = {
        "status": "invited",
        "email": email,
        "role": role,
        "invite_url": invite_url if str(values.get("SEMEAI_GATE_EXPOSE_INVITE_URL", "")).lower() in {"1", "true", "yes"} else None,
        "seats": get_team(auth, account_dir=root, env=values)["seats"],
    }
    if str(values.get("SEMEAI_GATE_EXPOSE_INVITE_URL", "")).lower() in {"1", "true", "yes"}:
        result["invite_token"] = token
    return result


def accept_invite(
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    root = _root(account_dir, values)
    token = str(payload.get("token") or payload.get("invite_token") or "").strip()
    if not token:
        raise AccountError("invite token is required")
    token_hash = _hash_secret(token)
    inv = None
    inv_path = None
    for path in (root / "invites").glob("inv_*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("token_hash") == token_hash and rec.get("status") == "pending":
            inv, inv_path = rec, path
            break
    if inv is None or inv_path is None:
        raise AccountError("invalid invite token", status_code=404)
    if _parse_iso(str(inv.get("expires_at") or "")) < datetime.now(timezone.utc):
        raise AccountError("invite expired", status_code=410)

    email = str(inv.get("email") or "")
    password = payload.get("password")
    # optional password for new users
    if password:
        from .accounts import _validate_password

        _validate_password(str(password))

    wpath, workspace = _load_workspace(root, str(inv.get("workspace_id")))
    members = _ensure_members(workspace)
    for m in members:
        if m.get("invite_token_hash") == token_hash or (
            str(m.get("email") or "").lower() == email.lower() and m.get("status") == "invited"
        ):
            m["status"] = "active"
            m["joined_at"] = _now()
            m.pop("invite_token_hash", None)
            m["role"] = inv.get("role") or m.get("role") or "member"
    workspace["members"] = members
    wpath.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")

    create_or_update_user_from_workspace(
        email=email,
        password=str(password) if password else None,
        workspace_id=str(inv.get("workspace_id")),
        role=str(inv.get("role") or "member"),
        account_dir=root,
        env=values,
    )

    inv["status"] = "accepted"
    inv["accepted_at"] = _now()
    inv_path.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "joined",
        "workspace_id": inv.get("workspace_id"),
        "workspace_name": inv.get("workspace_name"),
        "email": email,
        "role": inv.get("role"),
        "next_step": "Log in with your email and password to open the cabinet.",
    }


def remove_member(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    workspace_id = str(auth.get("workspace_id") or "")
    root = _root(account_dir, env)
    path, workspace = _load_workspace(root, workspace_id)
    _require_role(auth, workspace, {"owner", "admin"})
    email = _normalize_email(str(payload.get("email") or ""))
    members = _ensure_members(workspace)
    out = []
    removed = False
    for m in members:
        if str(m.get("email") or "").lower() == email:
            if m.get("role") == "owner":
                raise AccountError("cannot remove workspace owner")
            m["status"] = "removed"
            m["removed_at"] = _now()
            removed = True
        out.append(m)
    if not removed:
        raise AccountError("member not found", status_code=404)
    workspace["members"] = out
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "removed", "email": email}
