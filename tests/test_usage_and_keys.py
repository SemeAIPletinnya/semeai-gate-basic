from __future__ import annotations

from pathlib import Path

from semeai_gate_basic.keys import list_keys, rotate_key
from semeai_gate_basic.usage import (
    RateLimitError,
    get_usage,
    public_limits,
    record_check,
    record_public_demo_check,
)


def test_usage_meter_and_rate_limit(tmp_path: Path) -> None:
    env = {"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path), "SEMEAI_GATE_DAILY_CHECK_LIMIT": "2"}
    auth = {
        "workspace_id": "ws_test",
        "api_key_fingerprint": "abc123",
        "subscription": {"status": "active", "tier": "pilot"},
    }
    u1 = record_check(auth, env=env, enforce=True)
    assert u1["checks_today"] == 1
    u2 = record_check(auth, env=env, enforce=True)
    assert u2["remaining_today"] == 0
    try:
        record_check(auth, env=env, enforce=True)
        assert False, "expected rate limit"
    except RateLimitError:
        pass
    snap = get_usage(auth, env=env)
    assert snap["daily_limit"] == 2


def test_public_demo_rate_limit_is_separate_and_does_not_store_raw_identity() -> None:
    env = {"SEMEAI_GATE_PUBLIC_DEMO_RATE_LIMIT_PER_MINUTE": "1"}
    first = record_public_demo_check("test-client-demo-rate-limit", env=env)

    assert first["limit"] == 1
    assert first["remaining"] == 0
    assert first["raw_client_identity_stored"] is False
    assert public_limits(env=env)["demo_rate_limit"]["limit"] == 1

    try:
        record_public_demo_check("test-client-demo-rate-limit", env=env)
        assert False, "expected public demo rate limit"
    except RateLimitError as exc:
        assert exc.status_code == 429


def test_key_rotate_flow(tmp_path: Path) -> None:
    # Minimal workspace record
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir(parents=True)
    ws = {
        "workspace_id": "ws_1",
        "workspace_name": "Demo",
        "status": "active",
        "api_keys": [
            {
                "api_key_hash": "x",
                "api_key_fingerprint": "oldfp",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "raw_api_key_stored": False,
            }
        ],
    }
    (ws_dir / "ws_1.json").write_text(__import__("json").dumps(ws), encoding="utf-8")
    env = {"SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path)}
    auth = {"workspace_id": "ws_1", "api_key_fingerprint": "oldfp"}
    listed = list_keys(auth, env=env)
    assert listed["active_count"] == 1
    rotated = rotate_key(auth, env=env, label="new")
    assert rotated["api_key"].startswith("semeai_")
    assert rotated["revoked_fingerprint"] == "oldfp"
    listed2 = list_keys(auth, env=env)
    assert listed2["active_count"] == 1
