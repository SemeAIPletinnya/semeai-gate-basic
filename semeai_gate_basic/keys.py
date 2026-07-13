from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .accounts import _fingerprint_api_key, _hash_secret  # type: ignore


DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"


class KeyError_(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _root(account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return Path(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)


def _workspace_path(root: Path, workspace_id: str) -> Path:
    return root / "workspaces" / f"{workspace_id}.json"


def _load_workspace(root: Path, workspace_id: str) -> tuple[Path, dict[str, Any]]:
    path = _workspace_path(root, workspace_id)
    if not path.exists():
        raise KeyError_("workspace not found", status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KeyError_(f"workspace unreadable: {exc}", status_code=500) from exc
    return path, data


def list_keys(auth: Mapping[str, Any], *, account_dir: str | Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    workspace_id = str(auth.get("workspace_id") or "")
    if not workspace_id:
        raise KeyError_("workspace auth required", status_code=403)
    root = _root(account_dir, env)
    _, workspace = _load_workspace(root, workspace_id)
    keys = []
    for item in workspace.get("api_keys") or []:
        if not isinstance(item, dict):
            continue
        keys.append(
            {
                "api_key_fingerprint": item.get("api_key_fingerprint"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "revoked_at": item.get("revoked_at"),
                "label": item.get("label") or "default",
                "raw_api_key_stored": False,
            }
        )
    return {
        "schema_version": "0.1-keys",
        "workspace_id": workspace_id,
        "keys": keys,
        "active_count": sum(1 for k in keys if k.get("status") == "active"),
    }


def rotate_key(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    label: str = "rotated",
) -> dict[str, Any]:
    """Revoke current key fingerprint and issue a new API key (shown once)."""
    workspace_id = str(auth.get("workspace_id") or "")
    current_fp = str(auth.get("api_key_fingerprint") or "")
    if not workspace_id:
        raise KeyError_("workspace auth required", status_code=403)
    root = _root(account_dir, env)
    path, workspace = _load_workspace(root, workspace_id)
    now = datetime.now(timezone.utc).isoformat()
    api_keys = workspace.get("api_keys") if isinstance(workspace.get("api_keys"), list) else []
    for item in api_keys:
        if not isinstance(item, dict):
            continue
        if item.get("api_key_fingerprint") == current_fp and item.get("status") == "active":
            item["status"] = "revoked"
            item["revoked_at"] = now
            item["revoke_reason"] = "rotated"
    new_key = "semeai_" + secrets.token_urlsafe(32)
    new_fp = _fingerprint_api_key(new_key)
    api_keys.append(
        {
            "api_key_hash": _hash_secret(new_key),
            "api_key_fingerprint": new_fp,
            "status": "active",
            "created_at": now,
            "label": label or "rotated",
            "raw_api_key_stored": False,
        }
    )
    workspace["api_keys"] = api_keys
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schema_version": "0.1-keys",
        "status": "rotated",
        "workspace_id": workspace_id,
        "revoked_fingerprint": current_fp,
        "api_key": new_key,
        "api_key_fingerprint": new_fp,
        "api_key_issued": True,
        "raw_api_key_stored": False,
        "next_step": "Store the new API key now. It is shown once. Old key no longer works.",
    }


def revoke_key(
    auth: Mapping[str, Any],
    fingerprint: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    workspace_id = str(auth.get("workspace_id") or "")
    if not workspace_id:
        raise KeyError_("workspace auth required", status_code=403)
    fingerprint = str(fingerprint or "").strip()
    if not fingerprint:
        raise KeyError_("fingerprint required")
    root = _root(account_dir, env)
    path, workspace = _load_workspace(root, workspace_id)
    now = datetime.now(timezone.utc).isoformat()
    api_keys = workspace.get("api_keys") if isinstance(workspace.get("api_keys"), list) else []
    found = False
    active_left = 0
    for item in api_keys:
        if not isinstance(item, dict):
            continue
        if item.get("api_key_fingerprint") == fingerprint and item.get("status") == "active":
            item["status"] = "revoked"
            item["revoked_at"] = now
            item["revoke_reason"] = "user_revoke"
            found = True
        if item.get("status") == "active":
            active_left += 1
    if not found:
        raise KeyError_("active key fingerprint not found", status_code=404)
    if active_left == 0:
        # Prevent lockout: re-activate is not possible without admin; block full revoke.
        raise KeyError_("cannot revoke the last active key; rotate instead", status_code=400)
    workspace["api_keys"] = api_keys
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schema_version": "0.1-keys",
        "status": "revoked",
        "workspace_id": workspace_id,
        "revoked_fingerprint": fingerprint,
        "active_count": active_left,
    }
