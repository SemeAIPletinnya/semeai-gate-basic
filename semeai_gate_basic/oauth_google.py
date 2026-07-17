"""Google OAuth 2.0 (authorization code) for SaaS login/signup."""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .accounts import (
    AccountError,
    DEFAULT_ACCOUNT_DIR,
    _account_root,
    _now,
    register_workspace,
    verify_registration,
    _create_session,
    _workspaces_dir,
)
from .users import create_or_update_user_from_workspace, find_user_by_oauth, load_user_by_email


def oauth_status(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    client_id = str(values.get("SEMEAI_GATE_GOOGLE_CLIENT_ID") or "").strip()
    return {
        "google": {
            "enabled": bool(client_id and values.get("SEMEAI_GATE_GOOGLE_CLIENT_SECRET")),
            "client_id_configured": bool(client_id),
            "start_path": "/v0/oauth/google/start",
            "callback_path": "/v0/oauth/google/callback",
        }
    }


def google_start_url(
    *,
    env: Mapping[str, str] | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    client_id = str(values.get("SEMEAI_GATE_GOOGLE_CLIENT_ID") or "").strip()
    if not client_id:
        raise AccountError("Google OAuth is not configured", status_code=503)
    redirect_uri = str(
        values.get("SEMEAI_GATE_GOOGLE_REDIRECT_URI")
        or "https://api.semeai.tech/v0/oauth/google/callback"
    ).strip()
    st = state or secrets.token_urlsafe(16)
    # persist state
    root = _account_root(values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)
    (root / "oauth_state").mkdir(parents=True, exist_ok=True)
    (root / "oauth_state" / f"{st}.json").write_text(
        json.dumps({"created_at": _now(), "provider": "google"}, indent=2),
        encoding="utf-8",
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "state": st,
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"authorize_url": url, "state": st, "provider": "google"}


def google_callback(
    *,
    code: str,
    state: str,
    env: Mapping[str, str] | None = None,
    account_dir: str | Path | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)
    client_id = str(values.get("SEMEAI_GATE_GOOGLE_CLIENT_ID") or "").strip()
    client_secret = str(values.get("SEMEAI_GATE_GOOGLE_CLIENT_SECRET") or "").strip()
    redirect_uri = str(
        values.get("SEMEAI_GATE_GOOGLE_REDIRECT_URI")
        or "https://api.semeai.tech/v0/oauth/google/callback"
    ).strip()
    if not client_id or not client_secret:
        raise AccountError("Google OAuth is not configured", status_code=503)

    state_path = root / "oauth_state" / f"{state}.json"
    if not state_path.exists():
        raise AccountError("invalid OAuth state", status_code=400)
    try:
        state_path.unlink()
    except OSError:
        pass

    token_payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AccountError(f"Google token exchange failed: {body}", status_code=400) from exc

    access = tokens.get("access_token")
    if not access:
        raise AccountError("Google did not return access_token", status_code=400)

    ureq = urllib.request.Request(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access}"},
    )
    with urllib.request.urlopen(ureq, timeout=20) as resp:
        profile = json.loads(resp.read().decode("utf-8"))

    email = str(profile.get("email") or "").lower().strip()
    sub = str(profile.get("sub") or "")
    name = str(profile.get("name") or email.split("@")[0])
    if not email or not sub:
        raise AccountError("Google profile missing email", status_code=400)
    if profile.get("email_verified") is False:
        raise AccountError("Google email is not verified", status_code=403)

    # Existing OAuth user
    user = find_user_by_oauth("google", sub, account_dir=root, env=values)
    if user is None:
        found = load_user_by_email(email, account_dir=root, env=values)
        if found is not None:
            path, user = found
            oauth = user.get("oauth") if isinstance(user.get("oauth"), dict) else {}
            oauth["google"] = sub
            user["oauth"] = oauth
            path.write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            # New SaaS user: create workspace via register+auto-verify path
            # Generate random password (user uses OAuth); store oauth link
            random_password = secrets.token_urlsafe(18)
            reg = register_workspace(
                {
                    "email": email,
                    "password": random_password,
                    "company": f"{name}'s workspace",
                    "source": "oauth_google",
                },
                account_dir=root,
                env=values,
            )
            # extract verify token from URL
            vurl = reg["verification"]["verification_url"]
            token = vurl.split("#verify=", 1)[-1]
            verified = verify_registration(token, account_dir=root, env=values)
            create_or_update_user_from_workspace(
                email=email,
                password=random_password,
                workspace_id=str(verified["workspace_id"]),
                role="owner",
                name=name,
                oauth={"google": sub},
                account_dir=root,
                env=values,
            )
            return {
                "status": "authenticated",
                "provider": "google",
                "email": email,
                "workspace_id": verified["workspace_id"],
                "workspace_name": verified.get("workspace_name"),
                "session_token": verified.get("session_token"),
                "session_expires_at": verified.get("session_expires_at"),
                "new_user": True,
            }

    # Login existing
    ws_id = user.get("default_workspace_id")
    if not ws_id:
        memberships = user.get("memberships") or []
        if memberships:
            ws_id = memberships[0].get("workspace_id")
    if not ws_id:
        raise AccountError("user has no workspace", status_code=500)
    wpath = _workspaces_dir(root) / f"{ws_id}.json"
    if not wpath.exists():
        raise AccountError("workspace missing", status_code=404)
    workspace = json.loads(wpath.read_text(encoding="utf-8"))
    session = _create_session(wpath, workspace, env=values)
    return {
        "status": "authenticated",
        "provider": "google",
        "email": email,
        "workspace_id": ws_id,
        "workspace_name": workspace.get("workspace_name"),
        "session_token": session["session_token"],
        "session_expires_at": session["expires_at"],
        "new_user": False,
    }
