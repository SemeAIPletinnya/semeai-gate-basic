from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Mapping


DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"
_LOCK = Lock()

# Per-day check limits by subscription tier / plan.
TIER_DAILY_LIMITS = {
    # Product path: 5 free API checks, then USDT pilot / paid plan
    "unpaid": 5,
    "free": 5,
    "trial": 5,
    "pilot": 1_000,
    "starter": 1_000,
    "developer": 10_000,
    "growth": 10_000,
    "enterprise_review": 50_000,
    "scale": 50_000,
    "enterprise": 100_000,
}


class RateLimitError(PermissionError):
    def __init__(self, message: str, *, status_code: int = 429, retry_after: int = 60) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _root(account_dir: str | Path | None, env: Mapping[str, str] | None) -> Path:
    values = env or os.environ
    return Path(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)


def _day_key(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%d")


def _usage_path(root: Path, workspace_id: str, day: str) -> Path:
    return root / "usage" / workspace_id / f"{day}.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"day": path.stem, "checks": 0, "by_fingerprint": {}, "events": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"day": path.stem, "checks": 0, "by_fingerprint": {}, "events": []}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def daily_limit_for(auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> int:
    values = env or os.environ
    override = values.get("SEMEAI_GATE_DAILY_CHECK_LIMIT")
    if override and str(override).isdigit():
        return int(override)
    sub = auth.get("subscription") if isinstance(auth.get("subscription"), dict) else {}
    tier = str(sub.get("tier") or sub.get("plan") or "free").lower()
    status = str(sub.get("status") or "trial").lower()
    provider = str(sub.get("billing_provider") or "").lower()
    # Not paid yet → 5 free checks
    if status in {"unpaid", "pending_payment", "pending_review", "trial"}:
        return TIER_DAILY_LIMITS["free"]
    if tier in {"free", "unpaid", "trial"}:
        return TIER_DAILY_LIMITS["free"]
    if provider in {"", "not_configured"} and tier not in {"pilot", "starter", "growth", "scale", "enterprise", "developer"}:
        return TIER_DAILY_LIMITS["free"]
    return TIER_DAILY_LIMITS.get(tier, TIER_DAILY_LIMITS["pilot"])


def get_usage(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    workspace_id = str(auth.get("workspace_id") or "anonymous")
    day = _day_key()
    root = _root(account_dir, env)
    path = _usage_path(root, workspace_id, day)
    with _LOCK:
        data = _load(path)
    limit = daily_limit_for(auth, env=env)
    used = int(data.get("checks") or 0)
    remaining = max(0, limit - used)
    return {
        "schema_version": "0.1-usage",
        "workspace_id": workspace_id,
        "day": day,
        "checks_today": used,
        "daily_limit": limit,
        "remaining_today": remaining,
        "percent_used": round((used / limit) * 100, 2) if limit else 0,
        "by_fingerprint": data.get("by_fingerprint") or {},
        "rate_limit": {
            "window": "1 day UTC",
            "unit": "POST /v0/check",
            "enforced": True,
        },
    }


def record_check(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    enforce: bool = True,
) -> dict[str, Any]:
    """Increment usage and optionally enforce daily rate limit."""
    workspace_id = str(auth.get("workspace_id") or "anonymous")
    fingerprint = str(auth.get("api_key_fingerprint") or "unknown")
    day = _day_key()
    root = _root(account_dir, env)
    path = _usage_path(root, workspace_id, day)
    limit = daily_limit_for(auth, env=env)

    with _LOCK:
        data = _load(path)
        used = int(data.get("checks") or 0)
        if enforce and used >= limit:
            raise RateLimitError(
                f"daily check limit reached ({limit}). Upgrade plan or wait until next UTC day.",
                retry_after=3600,
            )
        used += 1
        data["checks"] = used
        by_fp = data.get("by_fingerprint") if isinstance(data.get("by_fingerprint"), dict) else {}
        by_fp[fingerprint] = int(by_fp.get(fingerprint) or 0) + 1
        data["by_fingerprint"] = by_fp
        events = data.get("events") if isinstance(data.get("events"), list) else []
        events.append({"ts": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint})
        data["events"] = events[-200:]
        _save(path, data)

    return get_usage(auth, account_dir=account_dir, env=env)


def public_limits(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "daily_limits_by_tier": TIER_DAILY_LIMITS,
        "window": "UTC day",
        "endpoint": "POST /v0/check",
        "demo_endpoint": "POST /v0/demo/check (not counted against workspace quota)",
        "configured_override_env": "SEMEAI_GATE_DAILY_CHECK_LIMIT",
    }
