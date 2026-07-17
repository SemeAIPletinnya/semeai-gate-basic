from __future__ import annotations

from pathlib import Path

import pytest

from semeai_gate_basic.accounts import register_workspace, verify_registration, login_with_password
from semeai_gate_basic.plans import list_plans
from semeai_gate_basic.teams import accept_invite, get_team, invite_member
from semeai_gate_basic.users import request_password_reset, reset_password_with_token
from urllib.parse import parse_qs, urlparse


def _token_from_url(url: str) -> str:
    return (parse_qs(urlparse(url).fragment).get("verify") or [""])[0]


def _register_verify(tmp_path: Path, email: str = "owner@example.com"):
    reg = register_workspace(
        {
            "email": email,
            "password": "secure-pass-99",
            "company": "Acme Gate",
        },
        account_dir=tmp_path,
        env={"SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech", "SEMEAI_GATE_EXPOSE_RESET_URL": "1"},
    )
    verified = verify_registration(
        _token_from_url(reg["verification"]["verification_url"]),
        account_dir=tmp_path,
        env={"SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech"},
    )
    return verified


def test_plans_catalog_has_variants() -> None:
    catalog = list_plans()
    ids = {p["id"] for p in catalog["plans"]}
    assert {"free", "starter", "growth", "scale", "enterprise"} <= ids
    assert catalog["payment_is_never_gate_authority"] is True


def test_password_reset_flow(tmp_path: Path) -> None:
    _register_verify(tmp_path)
    env = {
        "SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech",
        "SEMEAI_GATE_EXPOSE_RESET_URL": "1",
        "SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path),
    }
    forgot = request_password_reset("owner@example.com", account_dir=tmp_path, env=env)
    assert forgot["status"] == "ok"
    assert forgot.get("reset_token")
    reset = reset_password_with_token(
        forgot["reset_token"],
        "new-secure-pass-1",
        "new-secure-pass-1",
        account_dir=tmp_path,
        env=env,
    )
    assert reset["status"] == "password_updated"
    login = login_with_password(
        {"email": "owner@example.com", "password": "new-secure-pass-1"},
        account_dir=tmp_path,
        env=env,
    )
    assert login["status"] == "authenticated"


def test_team_invite_and_accept(tmp_path: Path) -> None:
    verified = _register_verify(tmp_path)
    env = {
        "SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech",
        "SEMEAI_GATE_EXPOSE_INVITE_URL": "1",
        "SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path),
    }
    auth = {
        "workspace_id": verified["workspace_id"],
        "workspace_name": verified["workspace_name"],
        "email": "owner@example.com",
        "auth_mode": "password_session",
        "subscription": {"status": "active", "tier": "growth", "plan": "growth"},
    }
    # bump plan seats via workspace file
    import json

    wpath = tmp_path / "workspaces" / f"{verified['workspace_id']}.json"
    ws = json.loads(wpath.read_text(encoding="utf-8"))
    ws["subscription"] = {"status": "active", "tier": "growth", "plan": "growth"}
    ws["plan"] = "growth"
    wpath.write_text(json.dumps(ws, indent=2), encoding="utf-8")

    inv = invite_member(auth, {"email": "mate@example.com", "role": "member"}, account_dir=tmp_path, env=env)
    assert inv["status"] == "invited"
    assert inv.get("invite_token")
    joined = accept_invite(
        {"token": inv["invite_token"], "password": "mate-pass-99"},
        account_dir=tmp_path,
        env=env,
    )
    assert joined["status"] == "joined"
    team = get_team(auth, account_dir=tmp_path, env=env)
    emails = {m["email"] for m in team["members"] if m["status"] == "active"}
    assert "mate@example.com" in emails
