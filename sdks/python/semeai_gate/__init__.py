"""SemeAI Gate Python SDK (thin client + local package re-export)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping

__all__ = ["check_ai_answer", "GateClient", "ACTION_TO_INTERNAL"]

ACTION_TO_INTERNAL = {
    "SHOW": "PROCEED",
    "REVIEW": "NEEDS_REVIEW",
    "BLOCK": "SILENCE",
}


def check_ai_answer(request: dict[str, Any], *, receipt_dir: str | None = None) -> dict[str, Any]:
    """Local package path (requires semeai_gate_basic installed in env)."""
    from semeai_gate_basic import check_ai_answer as _local

    return _local(request, receipt_dir=receipt_dir)


class GateClient:
    """Remote SaaS client for https://api.semeai.tech."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("SEMEAI_GATE_API_URL") or "https://api.semeai.tech").rstrip("/")
        self.timeout = timeout

    def check(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v0/check", body=dict(request))

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/v0/account")

    def usage(self) -> dict[str, Any]:
        return self._request("GET", "/v0/usage")

    def keys(self) -> dict[str, Any]:
        return self._request("GET", "/v0/keys")

    def rotate_key(self, label: str = "rotated") -> dict[str, Any]:
        return self._request("POST", "/v0/keys/rotate", body={"label": label})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "semeai-gate-python-sdk/0.2",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SemeAI Gate HTTP {exc.code}: {detail}") from exc
