"""HTTP routing for the authenticated workspace skill registry."""

from __future__ import annotations

import json
import os
import re
from http import HTTPStatus
from typing import Any

from .api import ApiAuthError, authenticate_headers
from .skill_registry import (
    SkillRegistryError,
    authenticate_skill_authority,
    decide_skill_candidate,
    get_skill_candidate,
    list_skill_candidates,
    retain_skill_candidate,
)


def handle_skill_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/v0/workspace/skills":
        try:
            auth = authenticate_headers(handler.headers, env=os.environ)
            limit = _safe_int((query.get("limit") or ["100"])[0], default=100)
            handler._send_json(list_skill_candidates(auth, env=os.environ, limit=limit))
        except (ApiAuthError, SkillRegistryError) as exc:
            handler._send_json(
                {"error": str(exc)},
                status=getattr(exc, "status_code", HTTPStatus.BAD_REQUEST),
            )
        return True

    detail = re.fullmatch(r"/v0/workspace/skills/(skillrec_[0-9a-f]{24})", path)
    if detail:
        try:
            auth = authenticate_headers(handler.headers, env=os.environ)
            handler._send_json(get_skill_candidate(auth, detail.group(1), env=os.environ))
        except (ApiAuthError, SkillRegistryError) as exc:
            handler._send_json(
                {"error": str(exc)},
                status=getattr(exc, "status_code", HTTPStatus.BAD_REQUEST),
            )
        return True
    return False


def handle_skill_post(handler: Any, path: str) -> bool:
    if path == "/v0/workspace/skills":
        try:
            auth = authenticate_headers(handler.headers, env=os.environ)
            payload = handler._read_json_body()
            result = retain_skill_candidate(auth, payload, env=os.environ)
            handler._send_json(
                result,
                status=HTTPStatus.CREATED if result.get("created") else HTTPStatus.OK,
            )
        except (ApiAuthError, SkillRegistryError, TypeError, ValueError, json.JSONDecodeError) as exc:
            handler._send_json(
                {"error": str(exc)},
                status=getattr(exc, "status_code", HTTPStatus.BAD_REQUEST),
            )
        return True

    decision = re.fullmatch(
        r"/v0/operator/workspaces/([A-Za-z0-9][A-Za-z0-9_-]{0,79})"
        r"/skills/(skillrec_[0-9a-f]{24})/decision",
        path,
    )
    if decision:
        try:
            authority = authenticate_skill_authority(handler.headers, env=os.environ)
            payload = handler._read_json_body()
            handler._send_json(
                decide_skill_candidate(
                    authority,
                    decision.group(1),
                    decision.group(2),
                    payload,
                    env=os.environ,
                )
            )
        except (SkillRegistryError, TypeError, ValueError, json.JSONDecodeError) as exc:
            handler._send_json(
                {"error": str(exc)},
                status=getattr(exc, "status_code", HTTPStatus.BAD_REQUEST),
            )
        return True
    return False


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
