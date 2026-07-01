from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api import (
    API_VERSION,
    ApiAuthError,
    api_health,
    authenticate_headers,
    check_api_answer,
    check_demo_answer,
    demo_account_profile,
    list_receipts,
    list_demo_scenarios,
    parse_api_keys,
    read_receipt,
)


class SemeAIGateHandler(BaseHTTPRequestHandler):
    server_version = "SemeAIGateBasic/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler naming
        self._send_json({"ok": True}, status=HTTPStatus.NO_CONTENT)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler naming
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/", "/health"}:
            self._send_json(api_health(), include_body=False)
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND, include_body=False)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in {"/", "/health"}:
            self._send_json(api_health())
            return

        if path == "/v0/demo/scenarios":
            self._send_json(list_demo_scenarios())
            return

        if path == "/v0/demo/account":
            self._send_json(demo_account_profile())
            return

        if path == "/v0/account":
            try:
                auth = authenticate_headers(self.headers)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            self._send_json(
                {
                    "api_version": API_VERSION,
                    "authenticated": auth["authenticated"],
                    "auth_mode": auth["auth_mode"],
                    "api_key_fingerprint": auth.get("api_key_fingerprint"),
                    "subscription": auth["subscription"],
                }
            )
            return

        if path == "/v0/receipts":
            try:
                auth = authenticate_headers(self.headers)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            query = parse_qs(parsed.query)
            limit = _safe_int((query.get("limit") or ["25"])[0], default=25)
            receipt_dir = os.environ.get("SEMEAI_GATE_RECEIPT_DIR") or None
            self._send_json(
                list_receipts(
                    receipt_dir=receipt_dir,
                    limit=limit,
                    api_key_fingerprint=auth.get("api_key_fingerprint"),
                )
            )
            return

        if path.startswith("/v0/receipts/"):
            try:
                auth = authenticate_headers(self.headers)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            receipt_id = path.rsplit("/", 1)[-1]
            receipt_dir = os.environ.get("SEMEAI_GATE_RECEIPT_DIR") or None
            receipt = read_receipt(
                receipt_id,
                receipt_dir=receipt_dir,
                api_key_fingerprint=auth.get("api_key_fingerprint"),
            )
            if receipt is None:
                self._send_json({"error": "receipt not found"}, status=HTTPStatus.NOT_FOUND)
            else:
                self._send_json(receipt)
            return

        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/v0/demo/check":
            try:
                payload = self._read_json_body()
                result = check_demo_answer(payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return

        if path != "/v0/check":
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json_body()
            result = check_api_answer(payload, headers=self.headers)
        except ApiAuthError as exc:
            self._send_json({"error": str(exc)}, status=exc.status_code)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except OSError as exc:
            self._send_json({"error": f"receipt store error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("SEMEAI_GATE_ACCESS_LOG", "").lower() in {"1", "true", "yes"}:
            super().log_message(format, *args)

    def _read_json_body(self) -> dict[str, Any]:
        length = _safe_int(self.headers.get("content-length", "0"), default=0)
        if length > 64 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        return payload

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: int | HTTPStatus = HTTPStatus.OK,
        include_body: bool = True,
    ) -> None:
        data = b"" if int(status) == HTTPStatus.NO_CONTENT else json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        origin = os.environ.get("SEMEAI_GATE_CORS_ORIGIN", "").strip()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "authorization, x-api-key, content-type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if data and include_body:
            self.wfile.write(data)


def run_server(*, host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), SemeAIGateHandler)
    print(f"SemeAI Gate Basic API listening on http://{host}:{port}")
    print("Endpoint: POST /v0/check")
    print("Default bind is local-first. Set host explicitly before exposing it.")
    httpd.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SemeAI Gate Basic API server.")
    parser.add_argument("--host", default=os.environ.get("SEMEAI_GATE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SEMEAI_GATE_PORT", "8787")))
    parser.add_argument("--receipt-dir", default=os.environ.get("SEMEAI_GATE_RECEIPT_DIR", ""))
    args = parser.parse_args()

    try:
        validate_server_auth_config(args.host)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.receipt_dir:
        Path(args.receipt_dir).mkdir(parents=True, exist_ok=True)
        os.environ["SEMEAI_GATE_RECEIPT_DIR"] = args.receipt_dir

    run_server(host=args.host, port=args.port)
    return 0


def _safe_int(value: str | None, *, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def validate_server_auth_config(host: str, *, env: dict[str, str] | None = None) -> None:
    values = env if env is not None else os.environ
    configured_keys = parse_api_keys(values.get("SEMEAI_GATE_API_KEYS", ""))
    if _is_public_bind_host(host) and not configured_keys:
        raise RuntimeError(
            "refusing to bind a public host without SEMEAI_GATE_API_KEYS; "
            "set API keys or bind to 127.0.0.1 for local development"
        )


def _is_public_bind_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized not in {"127.0.0.1", "localhost", "::1", "[::1]"}


if __name__ == "__main__":
    raise SystemExit(main())
