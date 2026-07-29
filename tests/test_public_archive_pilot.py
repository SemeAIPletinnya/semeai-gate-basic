from __future__ import annotations

from tools.run_public_archive_pilot import PILOT_TASKS, run_pilot


def test_public_archive_pilot_dry_run_contract() -> None:
    report = run_pilot()

    assert report["status"] == "DRY_RUN_NOT_HUMAN_EVALUATION"
    assert report["onlineIngestionEnabled"] is False
    assert report["externalModelCalls"] == 0
    assert report["privateArchiveIncluded"] is False
    assert report["summary"]["tasks"] == len(PILOT_TASKS) == 6
    assert report["summary"]["passed"] == 6
    assert report["summary"]["failed"] == 0
    assert report["summary"]["humanPilotCompleted"] is False
    assert all(task["citationsResolve"] for task in report["tasks"])
    assert all(task["releasedAnswerMatchesCandidate"] for task in report["tasks"])
    assert all(task["executionReceiptCreated"] is False for task in report["tasks"])
