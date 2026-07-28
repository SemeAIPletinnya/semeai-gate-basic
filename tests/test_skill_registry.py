from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from semeai_gate_basic.accounts import register_workspace, verify_registration
from semeai_gate_basic.api import api_health
from semeai_gate_basic.server import SemeAIGateHandler
from semeai_gate_basic.skill_registry import (
    SkillRegistryError,
    authenticate_skill_authority,
    decide_skill_candidate,
    get_skill_candidate,
    list_skill_candidates,
    retain_skill_candidate,
    skill_registry_configuration,
)


SKILL_HASH = "3b030d109ad876294cc6fe57525dfd5c190cbd61134ab0715f261de46db35c59"


def _auth(workspace_id: str = "ws_evidence_lab") -> dict[str, Any]:
    return {
        "authenticated": True,
        "workspace_id": workspace_id,
        "workspace_name": "Evidence Lab",
        "auth_mode": "password_session",
    }


def _candidate_payload() -> dict[str, Any]:
    return {
        "skill_id": "get-job",
        "name": "GET JOB",
        "version": "0.1-candidate",
        "skill_hash": SKILL_HASH,
        "evidence_cases": [
            {
                "case_id": "case-003",
                "domain": "moderation shadow transfer",
                "status": "COMPLETE LOCALLY",
                "outcome": "Bounded shadow-mode pilot retained without enforcement.",
                "evidence_refs": ["public:case-003-summary", "commit:4db2f36"],
                "tests": ["12 deterministic fixtures"],
                "commit": "4db2f36",
                "deployment": "NOT DEPLOYED",
            },
            {
                "case_id": "case-005",
                "domain": "historical repository archaeology",
                "status": "DEPLOYED",
                "outcome": "Bounded public evidence was admitted with privacy separation.",
                "evidence_refs": ["public:/genesis/"],
                "tests": ["25 historical admission assertions"],
                "deployment": "LIVE VERIFIED",
            },
        ],
        "evaluated_domains": ["moderation shadow", "historical repository archaeology"],
        "failures": ["No independent evaluator agreement was captured."],
        "limitations": ["Statistical improvement and universal transfer are not established."],
        "evaluation_context": {
            "evaluator": "bounded Case execution record",
            "authority": "evidence review only",
            "scope": "qualitative transfer evidence",
            "independent_evaluation": False,
        },
        "provenance": {
            "type": "user-authored frozen method",
            "summary": "Method hash and bounded Case evidence only.",
            "public_reference": "https://semeai.tech/skills/",
        },
    }


def test_skill_authority_fails_closed_and_configuration_exposes_no_secret() -> None:
    configuration = skill_registry_configuration(env={})
    assert configuration["workspace_persistence"] is True
    assert configuration["admission_authority_configured"] is False
    assert configuration["admission_enabled"] is False
    assert configuration["skill_admission_is_release_authority"] is False

    with pytest.raises(SkillRegistryError) as missing:
        authenticate_skill_authority({"Authorization": "Bearer any"}, env={})
    assert missing.value.status_code == 503

    authority = authenticate_skill_authority(
        {"Authorization": "Bearer skill-secret"},
        env={"SEMEAI_GATE_SKILL_AUTHORITY_KEY": "skill-secret"},
    )
    assert authority["skill_admission_authority"] is True
    assert authority["runtime_release_authority"] is False
    assert "skill-secret" not in json.dumps(authority)


def test_retain_list_get_is_workspace_scoped_idempotent_and_bounded(tmp_path: Path) -> None:
    env = {"SEMEAI_GATE_SKILL_DIR": str(tmp_path / "skills")}
    created = retain_skill_candidate(
        _auth(),
        _candidate_payload(),
        env=env,
        now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )
    assert created["created"] is True
    record = created["record"]
    assert record["admission"]["state"] == "REVIEW"
    assert record["admission"]["decision"] is None
    assert record["availability"]["available"] is False
    assert record["raw_skill_content_stored"] is False
    assert len(record["evidence"]["cases"]) == 2
    assert record["boundaries"]["candidate_retention_is_admission"] is False
    assert record["boundaries"]["skill_admission_is_runtime_release_authority"] is False

    repeated = retain_skill_candidate(_auth(), _candidate_payload(), env=env)
    assert repeated["created"] is False
    assert repeated["record"] == record

    listing = list_skill_candidates(_auth(), env=env)
    assert listing["count"] == 1
    assert listing["candidate_retention_is_admission"] is False
    assert get_skill_candidate(_auth(), record["record_id"], env=env) == record

    other = list_skill_candidates(_auth("ws_other_workspace"), env=env)
    assert other["count"] == 0
    with pytest.raises(SkillRegistryError) as hidden:
        get_skill_candidate(_auth("ws_other_workspace"), record["record_id"], env=env)
    assert hidden.value.status_code == 404

    stored = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert '"raw_skill":' not in stored
    assert '"source_code":' not in stored
    assert '"skill_content":' not in stored
    assert "skill-secret" not in stored


@pytest.mark.parametrize(
    "forbidden",
    [
        {"decision": "ADMITTED"},
        {"status": "ADMITTED"},
        {"availability": {"available": True}},
        {"raw_skill": "do something"},
        {"receipt": {"proof": True}},
    ],
)
def test_candidate_cannot_self_admit_or_store_raw_skill(
    tmp_path: Path,
    forbidden: dict[str, Any],
) -> None:
    payload = {**_candidate_payload(), **forbidden}
    with pytest.raises(SkillRegistryError):
        retain_skill_candidate(
            _auth(),
            payload,
            env={"SEMEAI_GATE_SKILL_DIR": str(tmp_path / "skills")},
        )


def test_operator_review_creates_distinct_deterministic_skill_receipt(tmp_path: Path) -> None:
    env = {
        "SEMEAI_GATE_SKILL_DIR": str(tmp_path / "skills"),
        "SEMEAI_GATE_SKILL_AUTHORITY_KEY": "skill-secret",
    }
    record = retain_skill_candidate(_auth(), _candidate_payload(), env=env)["record"]
    authority = authenticate_skill_authority(
        {"X-SemeAI-Skill-Authority": "skill-secret"},
        env=env,
    )
    decided_at = datetime(2026, 7, 28, 12, 30, tzinfo=timezone.utc)
    first = decide_skill_candidate(
        authority,
        record["workspace_id"],
        record["record_id"],
        {
            "decision": "REVIEW",
            "reason": "Evidence remains qualitative and has no independent evaluator.",
            "evaluator": "Case 006 operator",
        },
        env=env,
        now=decided_at,
    )
    second = decide_skill_candidate(
        authority,
        record["workspace_id"],
        record["record_id"],
        {
            "decision": "REVIEW",
            "reason": "Evidence remains qualitative and has no independent evaluator.",
            "evaluator": "Case 006 operator",
        },
        env=env,
        now=decided_at,
    )

    receipt = first["receipt"]
    assert receipt == second["receipt"]
    assert receipt["receipt_id"].startswith("skillreceipt_")
    assert receipt["receipt_type"] == "skill_admission_decision"
    assert receipt["decision"] == "REVIEW"
    assert receipt["integrity_hash_is_signature"] is False
    assert receipt["boundaries"]["receipt_is_universal_validity_proof"] is False
    assert receipt["boundaries"]["skill_admission_is_runtime_release_authority"] is False
    assert first["record"]["admission"]["state"] == "REVIEW"
    assert len(second["record"]["decision_history"]) == 1

    receipt_files = list((tmp_path / "skills" / "receipts").rglob("*.json"))
    assert len(receipt_files) == 1
    persisted = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert persisted["integrity_hash"] == receipt["integrity_hash"]
    assert "skill-secret" not in receipt_files[0].read_text(encoding="utf-8")


def test_admitted_decision_requires_explicit_environment_enablement(tmp_path: Path) -> None:
    env = {
        "SEMEAI_GATE_SKILL_DIR": str(tmp_path / "skills"),
        "SEMEAI_GATE_SKILL_AUTHORITY_KEY": "skill-secret",
    }
    record = retain_skill_candidate(_auth(), _candidate_payload(), env=env)["record"]
    authority = authenticate_skill_authority(
        {"Authorization": "Bearer skill-secret"},
        env=env,
    )
    with pytest.raises(SkillRegistryError) as disabled:
        decide_skill_candidate(
            authority,
            record["workspace_id"],
            record["record_id"],
            {"decision": "ADMITTED", "reason": "Operator decision."},
            env=env,
        )
    assert disabled.value.status_code == 409

    enabled = {**env, "SEMEAI_GATE_SKILL_ADMISSION_ENABLED": "true"}
    admitted = decide_skill_candidate(
        authority,
        record["workspace_id"],
        record["record_id"],
        {"decision": "ADMITTED", "reason": "Explicit bounded workspace admission."},
        env=enabled,
        now=datetime(2026, 7, 28, 13, 0, tzinfo=timezone.utc),
    )
    assert admitted["record"]["admission"]["state"] == "ADMITTED"
    assert admitted["record"]["availability"]["available"] is False
    assert admitted["record"]["boundaries"]["distribution_authorized"] is False


def test_http_workspace_skill_flow_and_operator_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_root = tmp_path / "accounts"
    monkeypatch.setenv("SEMEAI_GATE_ACCOUNT_DIR", str(account_root))
    monkeypatch.setenv("SEMEAI_GATE_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("SEMEAI_GATE_API_KEYS", "configured-static-key")
    monkeypatch.setenv("SEMEAI_GATE_SKILL_AUTHORITY_KEY", "skill-secret")
    monkeypatch.setenv("SEMEAI_GATE_SKILL_ADMISSION_ENABLED", "false")
    monkeypatch.setenv("SEMEAI_GATE_CORS_ORIGINS", "https://semeai.tech")

    registration = register_workspace(
        {
            "email": "skills@example.test",
            "password": "secure-pass-99",
            "company": "Skill Evidence Lab",
        },
        account_dir=account_root,
        env={"SEMEAI_GATE_PUBLIC_SITE_URL": "https://semeai.tech"},
    )
    token = registration["verification"]["verification_url"].split("#verify=", 1)[1]
    verified = verify_registration(token, account_dir=account_root)
    session_headers = {"Authorization": f"Bearer {verified['session_token']}"}

    server = ThreadingHTTPServer(("127.0.0.1", 0), SemeAIGateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        unauthenticated = _error_json(f"{base}/v0/workspace/skills")
        assert unauthenticated["status"] == 401

        retained = _post_json(
            f"{base}/v0/workspace/skills",
            _candidate_payload(),
            headers=session_headers,
            expected_status=201,
        )
        assert retained["created"] is True
        record = retained["record"]
        assert record["workspace_id"] == verified["workspace_id"]
        assert record["admission"]["state"] == "REVIEW"

        listing = _get_json(f"{base}/v0/workspace/skills", headers=session_headers)
        assert listing["count"] == 1
        detail = _get_json(
            f"{base}/v0/workspace/skills/{record['record_id']}",
            headers=session_headers,
        )
        assert detail["identity"]["skill_hash"] == SKILL_HASH

        denied = _post_json_error(
            f"{base}/v0/operator/workspaces/{verified['workspace_id']}"
            f"/skills/{record['record_id']}/decision",
            {"decision": "REVIEW", "reason": "Still under review."},
            headers={"Authorization": "Bearer wrong"},
        )
        assert denied["status"] == 403

        decision = _post_json(
            f"{base}/v0/operator/workspaces/{verified['workspace_id']}"
            f"/skills/{record['record_id']}/decision",
            {"decision": "REVIEW", "reason": "Still under bounded evidence review."},
            headers={"X-SemeAI-Skill-Authority": "skill-secret"},
        )
        assert decision["receipt"]["receipt_type"] == "skill_admission_decision"
        assert decision["receipt"]["decision"] == "REVIEW"

        health = _get_json(f"{base}/health")
        assert health["skill_registry"]["workspace_persistence"] is True
        assert health["skill_registry"]["admission_authority_configured"] is True
        assert health["skill_registry"]["admission_enabled"] is False
        assert "skill-secret" not in json.dumps(health)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_health_keeps_runtime_and_skill_authority_distinct() -> None:
    health = api_health(
        env={
            "SEMEAI_GATE_SKILL_AUTHORITY_KEY": "skill-secret",
            "SEMEAI_GATE_SKILL_ADMISSION_ENABLED": "true",
        }
    )
    assert health["internal_decisions"] == ["PROCEED", "NEEDS_REVIEW", "SILENCE"]
    assert health["public_actions"] == ["SHOW", "REVIEW", "BLOCK"]
    assert health["skill_registry"]["skill_admission_is_release_authority"] is False
    assert health["skill_registry"]["distribution_implemented"] is False
    assert "skill-secret" not in json.dumps(health)


def _get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == expected_status
        return json.loads(response.read().decode("utf-8"))


def _error_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, **json.loads(exc.read().decode("utf-8"))}
    raise AssertionError("request unexpectedly succeeded")


def _post_json_error(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, **json.loads(exc.read().decode("utf-8"))}
    raise AssertionError("request unexpectedly succeeded")
