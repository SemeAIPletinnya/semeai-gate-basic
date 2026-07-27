from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from semeai_gate_basic.github_workspace import (
    authenticate_session,
    create_session,
    get_benchmark_run,
    list_benchmark_runs,
    save_benchmark_run,
    upsert_github_user,
)
from semeai_gate_basic.repository_benchmark import (
    analyzer_configuration,
    collect_authorized_snapshot,
    run_canonical_analyzer,
)


FRONTEND_ROOT = Path(
    os.getenv("SEMEAI_FRONTEND_ROOT", r"D:\SemeAi\from git\semeai.tech")
)


def test_analyzer_configuration_requires_exact_available_canonical_core() -> None:
    core_path = FRONTEND_ROOT / "benchmark" / "assets" / "benchmark.js"
    source_hash = hashlib.sha256(core_path.read_bytes()).hexdigest()
    configured = analyzer_configuration(
        env={
            "SEMEAI_BENCHMARK_CORE_PATH": str(core_path),
            "SEMEAI_BENCHMARK_CORE_SHA256": source_hash,
            "SEMEAI_NODE_BINARY": "node",
        }
    )
    assert configured == {
        "configured": True,
        "source_sha256": source_hash,
        "policy_execution": "canonical-js-core",
    }
    mismatch = analyzer_configuration(
        env={
            "SEMEAI_BENCHMARK_CORE_PATH": str(core_path),
            "SEMEAI_BENCHMARK_CORE_SHA256": "0" * 64,
            "SEMEAI_NODE_BINARY": "node",
        }
    )
    assert mismatch["configured"] is False
    assert mismatch["source_sha256"] is None


def test_canonical_node_runner_matches_public_fallback_fixture(tmp_path: Path) -> None:
    snapshot = json.loads(
        (FRONTEND_ROOT / "benchmark" / "data" / "silence-as-control.snapshot.json").read_text(encoding="utf-8")
    )
    result = run_canonical_analyzer(
        {"snapshot": snapshot},
        env={
            "SEMEAI_BENCHMARK_CORE_PATH": str(FRONTEND_ROOT / "benchmark" / "assets" / "benchmark.js"),
            "SEMEAI_NODE_BINARY": "node",
        },
    )
    assert result["candidate"]["totalScore"] == 99
    assert [item["score"] for item in result["candidate"]["categoryScores"]] == [20, 20, 20, 15, 15, 5, 4]
    assert result["indicators"] == {"repositorySignal": 98, "evidenceDepth": 100, "gateDiscipline": 100}
    assert result["gate"]["decision"] == "REVIEW"
    assert result["visual"] == {"tier": 0, "visualSeed": 3, "visualPhase": "EXPANSION"}
    assert result["receipt"]["receipt_hash"] == "8fae1c025eb703961011df2ea083ec8d74cd85cf61b170b895b8e06e503f4897"


def test_authorized_capture_discards_document_text_and_preserves_bounded_analyzer_inputs() -> None:
    commit = "a" * 40

    def fetcher(url, token, accept, max_bytes, text_response):
        assert token == "ephemeral-installation-token"
        if url == "https://api.github.com/repositories/9001":
            return {
                "id": 9001,
                "full_name": "octo/private-evidence",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
                "owner": {"login": "octo"},
                "html_url": "https://github.com/octo/private-evidence",
                "stargazers_count": 0,
                "forks_count": 0,
                "open_issues_count": 0,
                "size": 12,
                "topics": [],
            }
        if "/commits/main" in url:
            return {"sha": commit, "commit": {"committer": {"date": "2026-07-22T12:00:00Z"}}}
        if url.endswith("/languages"):
            return {"Python": 1200}
        if "/releases?" in url:
            return []
        if url.endswith("/readme"):
            return "private prose that must not be retained"
        if "/git/trees/" in url:
            return {
                "tree": [
                    {"type": "blob", "path": "README.md"},
                    {"type": "blob", "path": "src/main.py"},
                    {"type": "blob", "path": "docs/runtime_decision_contract.md"},
                ],
                "truncated": False,
            }
        if url.endswith("/contents/docs/runtime_decision_contract.md"):
            return "PROCEED NEEDS_REVIEW SILENCE private contract prose"
        raise AssertionError(url)

    capture = collect_authorized_snapshot(
        {
            "github_repository_id": 9001,
            "full_name": "octo/private-evidence",
            "owner": "octo",
        },
        "ephemeral-installation-token",
        fetcher=fetcher,
    )
    serialized = json.dumps(capture)
    assert "private prose" not in serialized
    assert capture["paths"] == ["README.md", "src/main.py", "docs/runtime_decision_contract.md"]
    assert capture["document_terms"]["docs/runtime_decision_contract.md"] == {
        "proceed": True,
        "needsReview": True,
        "silence": True,
    }
    assert "normalized_evidence" not in capture["snapshot"]


def test_canonical_receipt_is_stored_unchanged_and_history_is_user_scoped(tmp_path: Path) -> None:
    snapshot = json.loads(
        (FRONTEND_ROOT / "benchmark" / "data" / "silence-as-control.snapshot.json").read_text(encoding="utf-8")
    )
    env = {
        "SEMEAI_BENCHMARK_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "SEMEAI_SESSION_COOKIE_SECRET": "runner-test-session-secret-that-is-at-least-32-bytes",
        "SEMEAI_BENCHMARK_CORE_PATH": str(FRONTEND_ROOT / "benchmark" / "assets" / "benchmark.js"),
        "SEMEAI_NODE_BINARY": "node",
    }
    user = upsert_github_user(
        {
            "id": 3030,
            "login": "receipt-owner",
            "avatar_url": "https://avatars.githubusercontent.com/u/3030?v=4",
            "name": "Receipt Owner",
        },
        env=env,
    )
    session = create_session(user["user_id"], env=env)
    auth = authenticate_session(session["session_token"], env=env)
    result = run_canonical_analyzer({"snapshot": snapshot}, env=env)
    repository = {
        "github_repository_id": 303030,
        "full_name": "SemeAIPletinnya/silence-as-control",
        "private": False,
    }
    saved = save_benchmark_run(auth, repository, result, env=env)
    detail = get_benchmark_run(auth, saved["run_id"], env=env)
    history = list_benchmark_runs(auth, repository_id=303030, env=env)

    assert detail["receipt"] == result["receipt"]
    assert detail["receipt_hash"] == "8fae1c025eb703961011df2ea083ec8d74cd85cf61b170b895b8e06e503f4897"
    assert detail["visual_seed"] == 3
    assert detail["visual_phase"] == "EXPANSION"
    assert history[0]["score_delta"] is None
    assert history[0]["category_deltas"] == {}
    assert "receipt" not in history[0]
