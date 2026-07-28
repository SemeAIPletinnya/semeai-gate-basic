"""Workspace-scoped skill evidence, admission decisions, and decision receipts.

Skill candidate retention is not admission. A configured operator authority is
required for an admission decision, and skill admission never becomes SaC/PoR
runtime release authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping


SKILL_RECORD_SCHEMA_VERSION = "semeai.workspace-skill-record.v0.1"
SKILL_RECEIPT_SCHEMA_VERSION = "semeai.skill-admission-receipt.v0.1"
DEFAULT_ACCOUNT_DIR = Path("outputs") / "api_accounts"
SKILL_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
RECORD_ID_RE = re.compile(r"^skillrec_[0-9a-f]{24}$")
WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_DECISIONS = {"REVIEW", "WITHHELD", "ADMITTED"}
_MUTATION_LOCK = threading.RLock()


class SkillRegistryError(ValueError):
    """Raised when a skill registry operation cannot be completed safely."""

    def __init__(self, message: str, *, status_code: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status_code = status_code


def skill_registry_configuration(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    return {
        "workspace_persistence": True,
        "admission_authority_configured": bool(
            str(values.get("SEMEAI_GATE_SKILL_AUTHORITY_KEY") or "").strip()
        ),
        "admission_enabled": _truthy(values.get("SEMEAI_GATE_SKILL_ADMISSION_ENABLED")),
        "candidate_retention_is_admission": False,
        "skill_admission_is_release_authority": False,
        "distribution_implemented": False,
    }


def authenticate_skill_authority(
    headers: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Authenticate the narrow, separately configured skill-decision authority."""

    values = env or os.environ
    configured = str(values.get("SEMEAI_GATE_SKILL_AUTHORITY_KEY") or "").strip()
    if not configured:
        raise SkillRegistryError(
            "skill admission authority is not configured",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    header_map = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    supplied = header_map.get("x-semeai-skill-authority", "")
    authorization = header_map.get("authorization", "")
    if not supplied and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied:
        raise SkillRegistryError(
            "skill admission authorization is required",
            status_code=HTTPStatus.UNAUTHORIZED,
        )
    if not hmac.compare_digest(supplied, configured):
        raise SkillRegistryError(
            "invalid skill admission authorization",
            status_code=HTTPStatus.FORBIDDEN,
        )
    return {
        "authenticated": True,
        "auth_mode": "skill_authority_key",
        "authority_fingerprint": _fingerprint(supplied),
        "skill_admission_authority": True,
        "runtime_release_authority": False,
    }


def retain_skill_candidate(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Retain an immutable, bounded skill-evidence snapshot in one workspace."""

    workspace_id = _authenticated_workspace_id(auth)
    if not isinstance(payload, Mapping):
        raise SkillRegistryError("request body must be a JSON object")
    forbidden = {
        "admission",
        "admission_decision",
        "availability",
        "decision",
        "decision_receipt",
        "receipt",
        "source_code",
        "raw_skill",
        "skill_content",
        "status",
    }
    if any(key in payload for key in forbidden):
        raise SkillRegistryError(
            "candidate retention cannot set admission, availability, receipt, or raw skill content"
        )

    identity = _normalize_identity(payload)
    evidence = {
        "cases": _normalize_evidence_cases(payload.get("evidence_cases") or []),
        "evaluated_domains": _string_list(
            payload.get("evaluated_domains"),
            field="evaluated_domains",
            limit=32,
            item_max=120,
        ),
        "failures": _string_list(
            payload.get("failures"),
            field="failures",
            limit=32,
            item_max=500,
        ),
        "limitations": _string_list(
            payload.get("limitations"),
            field="limitations",
            limit=32,
            item_max=500,
        ),
    }
    evaluation_context = _normalize_evaluation_context(payload.get("evaluation_context"))
    provenance = _normalize_provenance(payload.get("provenance"))
    record_id = _record_id(workspace_id, identity)
    captured_at = _iso(now or datetime.now(timezone.utc))
    record = {
        "schema_version": SKILL_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "workspace_id": workspace_id,
        "identity": identity,
        "provenance": provenance,
        "evidence": evidence,
        "evaluation_context": evaluation_context,
        "admission": {
            "state": "REVIEW",
            "decision": None,
            "decision_reason": None,
            "decision_timestamp": None,
            "authority": None,
            "receipt_id": None,
            "receipt_integrity_hash": None,
        },
        "decision_history": [],
        "availability": {
            "available": False,
            "installable": False,
            "marketplace_ready": False,
        },
        "boundaries": _boundaries(),
        "created_at": captured_at,
        "updated_at": captured_at,
        "raw_skill_content_stored": False,
    }

    path = _record_path(workspace_id, record_id, env=env)
    with _MUTATION_LOCK:
        existing = _read_json(path)
        if existing is not None:
            return {"created": False, "record": _public_record(existing)}
        _atomic_json(path, record)
    return {"created": True, "record": _public_record(record)}


def list_skill_candidates(
    auth: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    workspace_id = _authenticated_workspace_id(auth)
    safe_limit = max(1, min(int(limit), 100))
    directory = _records_root(env=env) / workspace_id
    records: list[dict[str, Any]] = []
    if directory.exists():
        for path in sorted(directory.glob("skillrec_*.json"), reverse=True):
            value = _read_json(path)
            if value is None or value.get("workspace_id") != workspace_id:
                continue
            records.append(_public_record(value))
            if len(records) >= safe_limit:
                break
    return {
        "schema_version": SKILL_RECORD_SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "records": records,
        "count": len(records),
        "candidate_retention_is_admission": False,
    }


def get_skill_candidate(
    auth: Mapping[str, Any],
    record_id: str,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    workspace_id = _authenticated_workspace_id(auth)
    clean_record_id = _validated_record_id(record_id)
    record = _read_json(_record_path(workspace_id, clean_record_id, env=env))
    if record is None or record.get("workspace_id") != workspace_id:
        raise SkillRegistryError("skill record not found", status_code=HTTPStatus.NOT_FOUND)
    return _public_record(record)


def decide_skill_candidate(
    authority: Mapping[str, Any],
    workspace_id: str,
    record_id: str,
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append an operator decision and immutable skill-admission receipt."""

    if not authority.get("authenticated") or not authority.get("skill_admission_authority"):
        raise SkillRegistryError(
            "skill admission authority is required",
            status_code=HTTPStatus.UNAUTHORIZED,
        )
    clean_workspace_id = _validated_workspace_id(workspace_id)
    clean_record_id = _validated_record_id(record_id)
    if not isinstance(payload, Mapping):
        raise SkillRegistryError("request body must be a JSON object")
    decision = _text(payload.get("decision"), field="decision", max_len=20).upper()
    if decision not in ALLOWED_DECISIONS:
        raise SkillRegistryError("decision must be REVIEW, WITHHELD, or ADMITTED")
    values = env or os.environ
    if decision == "ADMITTED" and not _truthy(values.get("SEMEAI_GATE_SKILL_ADMISSION_ENABLED")):
        raise SkillRegistryError(
            "skill admission is disabled for this environment",
            status_code=HTTPStatus.CONFLICT,
        )
    reason = _text(payload.get("reason"), field="reason", max_len=1000)
    evaluator = _optional_text(payload.get("evaluator"), max_len=160)
    decided_at = _iso(now or datetime.now(timezone.utc))
    record_path = _record_path(clean_workspace_id, clean_record_id, env=values)

    with _MUTATION_LOCK:
        record = _read_json(record_path)
        if record is None or record.get("workspace_id") != clean_workspace_id:
            raise SkillRegistryError("skill record not found", status_code=HTTPStatus.NOT_FOUND)

        evidence_snapshot_hash = _sha256(
            _canonical_json(
                {
                    "identity": record.get("identity"),
                    "provenance": record.get("provenance"),
                    "evidence": record.get("evidence"),
                    "evaluation_context": record.get("evaluation_context"),
                }
            )
        )
        authority_record = {
            "type": "configured_skill_authority",
            "fingerprint": str(authority.get("authority_fingerprint") or ""),
            "evaluator": evaluator,
        }
        receipt_body = {
            "schema_version": SKILL_RECEIPT_SCHEMA_VERSION,
            "receipt_type": "skill_admission_decision",
            "workspace_id": clean_workspace_id,
            "skill_record_id": clean_record_id,
            "skill_identity": record.get("identity"),
            "evidence_snapshot_hash": evidence_snapshot_hash,
            "decision": decision,
            "decision_reason": reason,
            "decision_timestamp": decided_at,
            "authority": authority_record,
            "boundaries": _boundaries(),
        }
        integrity_hash = _sha256(_canonical_json(receipt_body))
        receipt_id = f"skillreceipt_{integrity_hash[:24]}"
        receipt = {
            **receipt_body,
            "receipt_id": receipt_id,
            "integrity_hash": integrity_hash,
            "integrity_hash_is_signature": False,
        }
        _atomic_json(_receipt_path(clean_workspace_id, receipt_id, env=values), receipt)

        history = record.get("decision_history")
        if not isinstance(history, list):
            history = []
        if not any(item.get("receipt_id") == receipt_id for item in history if isinstance(item, dict)):
            history.append(
                {
                    "decision": decision,
                    "decision_reason": reason,
                    "decision_timestamp": decided_at,
                    "authority": authority_record,
                    "receipt_id": receipt_id,
                    "receipt_integrity_hash": integrity_hash,
                }
            )
        record["decision_history"] = history
        record["admission"] = {
            "state": decision,
            "decision": decision,
            "decision_reason": reason,
            "decision_timestamp": decided_at,
            "authority": authority_record,
            "receipt_id": receipt_id,
            "receipt_integrity_hash": integrity_hash,
        }
        record["availability"] = {
            "available": False,
            "installable": False,
            "marketplace_ready": False,
        }
        record["updated_at"] = decided_at
        _atomic_json(record_path, record)

    return {"record": _public_record(record), "receipt": receipt}


def _normalize_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    skill_id = _text(payload.get("skill_id"), field="skill_id", max_len=64).lower()
    if not SKILL_ID_RE.fullmatch(skill_id):
        raise SkillRegistryError("skill_id contains unsupported characters")
    version = _text(payload.get("version"), field="version", max_len=80)
    skill_hash = _text(
        payload.get("skill_hash") or payload.get("source_skill_sha256"),
        field="skill_hash",
        max_len=64,
    ).lower()
    if not SHA256_RE.fullmatch(skill_hash):
        raise SkillRegistryError("skill_hash must be a lowercase SHA-256 value")
    name = _text(payload.get("name") or skill_id, field="name", max_len=120)
    return {"skill_id": skill_id, "name": name, "version": version, "skill_hash": skill_hash}


def _normalize_evidence_cases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SkillRegistryError("evidence_cases must be an array")
    if len(value) > 32:
        raise SkillRegistryError("evidence_cases exceeds the 32-case limit")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise SkillRegistryError("each evidence case must be an object")
        case_id = _text(item.get("case_id"), field="case_id", max_len=100)
        if case_id in seen:
            raise SkillRegistryError(f"duplicate evidence case: {case_id}")
        seen.add(case_id)
        cases.append(
            {
                "case_id": case_id,
                "domain": _optional_text(item.get("domain"), max_len=160),
                "status": _optional_text(item.get("status"), max_len=80),
                "outcome": _optional_text(item.get("outcome"), max_len=500),
                "summary": _optional_text(item.get("summary"), max_len=1000),
                "evidence_refs": _string_list(
                    item.get("evidence_refs"),
                    field=f"{case_id}.evidence_refs",
                    limit=24,
                    item_max=500,
                ),
                "tests": _string_list(
                    item.get("tests"),
                    field=f"{case_id}.tests",
                    limit=24,
                    item_max=500,
                ),
                "commit": _optional_text(item.get("commit"), max_len=80),
                "deployment": _optional_text(item.get("deployment"), max_len=160),
            }
        )
    return cases


def _normalize_evaluation_context(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise SkillRegistryError("evaluation_context must be an object")
    return {
        "evaluator": _optional_text(value.get("evaluator"), max_len=160),
        "authority": _optional_text(value.get("authority"), max_len=200),
        "scope": _optional_text(value.get("scope"), max_len=500),
        "independent_evaluation": bool(value.get("independent_evaluation", False)),
        "declared_metadata_is_admission_authority": False,
    }


def _normalize_provenance(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise SkillRegistryError("provenance must be an object")
    return {
        "type": _optional_text(value.get("type"), max_len=100),
        "summary": _optional_text(value.get("summary"), max_len=500),
        "public_reference": _optional_text(value.get("public_reference"), max_len=500),
    }


def _authenticated_workspace_id(auth: Mapping[str, Any]) -> str:
    if not auth.get("authenticated"):
        raise SkillRegistryError("authentication required", status_code=HTTPStatus.UNAUTHORIZED)
    workspace_id = str(auth.get("workspace_id") or "").strip()
    if not workspace_id:
        raise SkillRegistryError(
            "a backend-backed account workspace is required",
            status_code=HTTPStatus.FORBIDDEN,
        )
    return _validated_workspace_id(workspace_id)


def _validated_workspace_id(value: str) -> str:
    clean = str(value or "").strip()
    if not WORKSPACE_ID_RE.fullmatch(clean):
        raise SkillRegistryError("invalid workspace id")
    return clean


def _validated_record_id(value: str) -> str:
    clean = str(value or "").strip()
    if not RECORD_ID_RE.fullmatch(clean):
        raise SkillRegistryError("invalid skill record id")
    return clean


def _record_id(workspace_id: str, identity: Mapping[str, str]) -> str:
    seed = "\0".join(
        [
            workspace_id,
            identity["skill_id"],
            identity["version"],
            identity["skill_hash"],
        ]
    )
    return f"skillrec_{_sha256(seed.encode('utf-8'))[:24]}"


def _registry_root(*, env: Mapping[str, str] | None = None) -> Path:
    values = env or os.environ
    explicit = str(values.get("SEMEAI_GATE_SKILL_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    account_root = Path(
        str(values.get("SEMEAI_GATE_ACCOUNT_DIR") or "").strip() or DEFAULT_ACCOUNT_DIR
    )
    return account_root / "skill_registry"


def _records_root(*, env: Mapping[str, str] | None = None) -> Path:
    return _registry_root(env=env) / "records"


def _record_path(
    workspace_id: str,
    record_id: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return _records_root(env=env) / _validated_workspace_id(workspace_id) / f"{_validated_record_id(record_id)}.json"


def _receipt_path(
    workspace_id: str,
    receipt_id: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if not re.fullmatch(r"skillreceipt_[0-9a-f]{24}", str(receipt_id or "")):
        raise SkillRegistryError("invalid skill receipt id")
    return (
        _registry_root(env=env)
        / "receipts"
        / _validated_workspace_id(workspace_id)
        / f"{receipt_id}.json"
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        temporary.write_text(serialized, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillRegistryError(
            "skill registry storage is unreadable",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        ) from exc
    return value if isinstance(value, dict) else None


def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record.get("schema_version"),
        "record_id": record.get("record_id"),
        "workspace_id": record.get("workspace_id"),
        "identity": record.get("identity"),
        "provenance": record.get("provenance"),
        "evidence": record.get("evidence"),
        "evaluation_context": record.get("evaluation_context"),
        "admission": record.get("admission"),
        "decision_history": record.get("decision_history") or [],
        "availability": record.get("availability"),
        "boundaries": record.get("boundaries"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "raw_skill_content_stored": False,
    }


def _boundaries() -> dict[str, bool]:
    return {
        "generation_is_admission_authority": False,
        "candidate_retention_is_admission": False,
        "evidence_count_is_quality": False,
        "skill_admission_is_runtime_release_authority": False,
        "receipt_is_universal_validity_proof": False,
        "distribution_authorized": False,
    }


def _text(value: Any, *, field: str, max_len: int) -> str:
    clean = " ".join(str(value or "").split()).strip()
    if not clean:
        raise SkillRegistryError(f"{field} is required")
    if len(clean) > max_len:
        raise SkillRegistryError(f"{field} exceeds {max_len} characters")
    return clean


def _optional_text(value: Any, *, max_len: int) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    clean = " ".join(str(value).split()).strip()
    if len(clean) > max_len:
        raise SkillRegistryError(f"text value exceeds {max_len} characters")
    return clean


def _string_list(
    value: Any,
    *,
    field: str,
    limit: int,
    item_max: int,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SkillRegistryError(f"{field} must be an array")
    if len(value) > limit:
        raise SkillRegistryError(f"{field} exceeds the {limit}-item limit")
    result: list[str] = []
    for item in value:
        clean = " ".join(str(item or "").split()).strip()
        if not clean:
            continue
        if len(clean) > item_max:
            raise SkillRegistryError(f"{field} contains an item longer than {item_max} characters")
        if clean not in result:
            result.append(clean)
    return result


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
