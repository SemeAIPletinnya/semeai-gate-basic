from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any

from .gate import check_ai_answer


INDEX_SCHEMA = "semeai.axiom-public-evidence-index.v0.1"
BUNDLE_SCHEMA = "semeai.axiom-evidence-bundle.v0.1"
CANDIDATE_SCHEMA = "semeai.axiom-candidate.v0.1"
RESPONSE_SCHEMA = "semeai.axiom-public-answer.v0.1"
DEFAULT_INDEX_PATH = Path(__file__).with_name("data") / "axiom_public_evidence.json"
MAX_QUERY_LENGTH = 256
MAX_RESULTS = 8


class PublicArchiveError(ValueError):
    """Raised when a public archive request or bundled index is invalid."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def load_public_index(index_path: str | Path | None = None) -> dict[str, Any]:
    """Load the frozen PUBLIC-only index without network or private archive access."""

    target = Path(index_path or DEFAULT_INDEX_PATH)
    try:
        index = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicArchiveError("Axiom public evidence index is unavailable", status_code=500) from exc

    if not isinstance(index, dict) or index.get("schemaVersion") != INDEX_SCHEMA:
        raise PublicArchiveError("Axiom public evidence index contract is invalid", status_code=500)

    policy = index.get("visibilityPolicy")
    if (
        not isinstance(policy, dict)
        or policy.get("allowed") != ["PUBLIC"]
        or policy.get("privateArchiveIncluded") is not False
        or policy.get("rawArchiveIncluded") is not False
        or policy.get("onlineIngestionEnabled") is not False
    ):
        raise PublicArchiveError("Axiom public evidence visibility policy is invalid", status_code=500)

    authority = index.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("retrievalIsTruth") is not False
        or authority.get("retrievalIsReleaseAuthority") is not False
        or authority.get("candidateIsReleasedAnswer") is not False
        or authority.get("releaseAuthority") != "SaC/PoR Gate"
    ):
        raise PublicArchiveError("Axiom public evidence authority contract is invalid", status_code=500)

    entries = index.get("entries")
    if not isinstance(entries, list):
        raise PublicArchiveError("Axiom public evidence entries are invalid", status_code=500)

    source_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("visibility") != "PUBLIC":
            raise PublicArchiveError("Axiom index contains non-public evidence", status_code=500)
        source_id = str(entry.get("sourceId") or "").strip()
        if not source_id or source_id in source_ids:
            raise PublicArchiveError("Axiom index source identities are invalid", status_code=500)
        if not all(str(entry.get(key) or "").strip() for key in ("title", "summary", "evidenceType", "route")):
            raise PublicArchiveError("Axiom index entry contract is incomplete", status_code=500)
        if not str(entry.get("route") or "").startswith("/"):
            raise PublicArchiveError("Axiom index route must be repository-relative", status_code=500)
        source = entry.get("source")
        if not isinstance(source, dict) or not all(
            str(source.get(key) or "").strip() for key in ("repository", "path", "sha256", "identity")
        ):
            raise PublicArchiveError("Axiom index source provenance is incomplete", status_code=500)
        source_ids.add(source_id)

    return deepcopy(index)


def retrieve_public_evidence(
    payload: dict[str, Any],
    *,
    index_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic evidence bundle. Retrieval is neither truth nor release."""

    if not isinstance(payload, dict):
        raise PublicArchiveError("request body must be a JSON object")
    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        raise PublicArchiveError("question must be a non-empty string")
    if len(question) > MAX_QUERY_LENGTH:
        raise PublicArchiveError(f"question must be at most {MAX_QUERY_LENGTH} characters")

    route_context = _route_context(payload.get("routeContext") or payload.get("route"))
    limit = _bounded_limit(payload.get("limit"))
    query_tokens = _tokens(question)
    index = load_public_index(index_path)

    matches: list[tuple[int, dict[str, Any]]] = []
    if query_tokens:
        for entry in index["entries"]:
            score = _score_entry(entry, query_tokens, route_context)
            if score > 0:
                matches.append((score, entry))
    matches.sort(key=lambda item: (-item[0], str(item[1]["sourceId"])))
    matches = matches[:limit]

    evidence = [_public_evidence(entry, score) for score, entry in matches]
    return {
        "schemaVersion": BUNDLE_SCHEMA,
        "query": question,
        "routeContext": route_context,
        "noEvidence": not evidence,
        "evidence": evidence,
        "authority": {
            "retrievalIsTruth": False,
            "retrievalIsReleaseAuthority": False,
            "candidateAnswerProduced": False,
            "releaseAuthority": "SaC/PoR Gate",
        },
    }


def build_archive_candidate(
    payload: dict[str, Any],
    *,
    index_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic pre-Gate candidate from the retrieved public evidence."""

    bundle = retrieve_public_evidence(payload, index_path=index_path)
    if bundle["noEvidence"]:
        return {
            "schemaVersion": CANDIDATE_SCHEMA,
            "candidate": None,
            "evidenceBundle": bundle,
            "releaseEvaluation": "NOT_EVALUATED",
        }

    lines = ["Based only on the retrieved public evidence:"]
    sources = ["Sources:"]
    for number, item in enumerate(bundle["evidence"], start=1):
        lines.append(f"{number}. {item['title']} — {item['summary']} [{number}]")
        sources.append(f"[{number}] {item['sourceId']} {item['route']}")
    candidate_text = "\n".join([*lines, "", *sources])
    candidate_hash = _sha256(candidate_text)
    identity_seed = json.dumps(
        {
            "query": bundle["query"],
            "routeContext": bundle["routeContext"],
            "sourceIds": [item["sourceId"] for item in bundle["evidence"]],
            "candidateHash": candidate_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return {
        "schemaVersion": CANDIDATE_SCHEMA,
        "candidate": {
            "candidateId": f"axiom-candidate-{_sha256(identity_seed)[:16]}",
            "candidateHash": candidate_hash,
            "candidateText": candidate_text,
            "state": "CANDIDATE_NOT_RELEASE_AUTHORITY",
        },
        "evidenceBundle": bundle,
        "releaseEvaluation": "NOT_EVALUATED",
    }


def release_public_archive_answer(
    payload: dict[str, Any],
    *,
    receipt_dir: str | Path | None = None,
    index_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run candidate output through the existing Gate and expose only its decision."""

    built = build_archive_candidate(payload, index_path=index_path)
    bundle = built["evidenceBundle"]
    candidate = built["candidate"]
    if candidate is None:
        return {
            "schemaVersion": RESPONSE_SCHEMA,
            "query": bundle["query"],
            "routeContext": bundle["routeContext"],
            "evidenceBundle": bundle,
            "candidate": None,
            "release": {
                "gateEvaluated": False,
                "action": None,
                "internalDecision": None,
                "showToUser": False,
                "decisionReceiptId": None,
                "receipt_id": None,
                "executionReceiptId": None,
                "reason": "No matching public evidence; no candidate was generated.",
                "auditPreserved": None,
            },
            "releasedAnswer": None,
            "authority": _response_authority(),
        }

    evidence = bundle["evidence"]
    gate_request = {
        "user_message": bundle["query"],
        "ai_answer": candidate["candidateText"],
        "business_data": {
            "supported_claims": [item["summary"] for item in evidence],
            "source_ids": [item["sourceId"] for item in evidence],
        },
        "business_rules": {"block_unsupported_claims": True},
        "business_context": {
            "conversation_topic": "public_archive",
            "expected_answer_scope": "public_evidence_summary",
        },
        "business_risk": "unsupported_product_claim",
        "metadata": {
            "trace_contract": "semeai.axiom-release-trace.v0.1",
            "candidate_id": candidate["candidateId"],
            "candidate_hash": candidate["candidateHash"],
            "route_context": bundle["routeContext"],
            "source_ids": [item["sourceId"] for item in evidence],
        },
    }
    gate = check_ai_answer(gate_request, receipt_dir=receipt_dir)
    show_to_user = bool(gate["show_to_user"])
    if show_to_user != (gate["action"] == "SHOW"):
        raise PublicArchiveError("Gate returned an inconsistent release decision", status_code=500)

    decision_receipt_id = str(gate["audit_id"])
    return {
        "schemaVersion": RESPONSE_SCHEMA,
        "query": bundle["query"],
        "routeContext": bundle["routeContext"],
        "evidenceBundle": bundle,
        "candidate": {
            "candidateId": candidate["candidateId"],
            "candidateHash": candidate["candidateHash"],
            "candidateTextIncluded": False,
            "state": "CANDIDATE_EVALUATED_BY_GATE",
        },
        "release": {
            "gateEvaluated": True,
            "action": gate["action"],
            "internalDecision": gate["internal_decision"],
            "showToUser": show_to_user,
            "decisionReceiptId": decision_receipt_id,
            "receipt_id": decision_receipt_id,
            "executionReceiptId": None,
            "reason": gate["reason"],
            "riskDetails": deepcopy(gate["risk_details"]),
            "nextStep": gate["next_step"],
            "auditPreserved": bool(gate["audit_preserved"]),
            "contextIntegrity": gate["context_integrity"],
        },
        "releasedAnswer": candidate["candidateText"] if show_to_user else None,
        "authority": _response_authority(),
    }


def _response_authority() -> dict[str, Any]:
    return {
        "generationIsReleaseAuthority": False,
        "candidateIsReleasedAnswer": False,
        "retrievalIsTruth": False,
        "releaseAuthority": "SaC/PoR Gate",
        "postGateMutationAllowed": False,
        "decisionAndExecutionReceiptsAreDistinct": True,
    }


def _normalize(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    clean = "".join(char if char.isalnum() or char in "_-" else " " for char in normalized)
    return " ".join(clean.split())


def _tokens(value: Any) -> list[str]:
    return sorted({token for token in _normalize(value).split() if len(token) >= 2})


def _route_context(value: Any) -> str | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    return normalized.split()[0][:32]


def _bounded_limit(value: Any) -> int:
    if value in (None, ""):
        return 5
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PublicArchiveError("limit must be an integer from 1 to 8") from exc
    if not 1 <= parsed <= MAX_RESULTS:
        raise PublicArchiveError("limit must be an integer from 1 to 8")
    return parsed


def _score_entry(entry: dict[str, Any], query_tokens: list[str], route_context: str | None) -> int:
    searchable = _normalize(
        " ".join(
            [
                str(entry.get("sourceId") or ""),
                str(entry.get("title") or ""),
                str(entry.get("summary") or ""),
                str(entry.get("evidenceType") or ""),
                str(entry.get("admissionState") or ""),
                str(entry.get("date") or ""),
                str(entry.get("version") or ""),
                *(str(item) for item in entry.get("keywords") or []),
                *(str(item) for item in entry.get("routeContexts") or []),
                json.dumps(entry.get("facts") or {}, ensure_ascii=False, sort_keys=True),
            ]
        )
    )
    title = _normalize(entry.get("title"))
    keywords = [_normalize(item) for item in entry.get("keywords") or []]
    score = 0
    for token in query_tokens:
        if token in searchable:
            score += 3 if len(token) >= 6 else 2
        if token in title:
            score += 3
        if any(token in keyword for keyword in keywords):
            score += 2
    if score > 0 and route_context and route_context in (entry.get("routeContexts") or []):
        score += 2
    return score


def _public_evidence(entry: dict[str, Any], score: int) -> dict[str, Any]:
    return {
        "sourceId": entry["sourceId"],
        "title": entry["title"],
        "summary": entry["summary"],
        "evidenceType": entry["evidenceType"],
        "visibility": "PUBLIC",
        "admissionState": entry.get("admissionState"),
        "date": entry.get("date"),
        "version": entry.get("version"),
        "route": entry["route"],
        "source": deepcopy(entry["source"]),
        "facts": deepcopy(entry.get("facts") or {}),
        "relevanceScore": score,
        "contentTrust": "UNTRUSTED_DATA",
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
