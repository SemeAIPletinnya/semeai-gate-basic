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

from .accounts import (
    AccountError,
    login_with_password,
    logout_session,
    register_workspace,
    verify_registration,
)
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
    public_status,
    read_receipt,
)
from .keys import KeyError_ as KeyManageError
from .keys import list_keys, revoke_key, rotate_key
from .usage import RateLimitError, get_usage
from .admin import (
    AdminActionError,
    AdminAuthError,
    activate_workspace_after_manual_review,
    authenticate_admin_headers,
    list_admin_workspaces,
    list_billing_reviews,
)
from .billing import (
    BillingError,
    billing_status,
    create_manual_crypto_intent,
    submit_manual_crypto_txid,
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

        if path == "/v0/status":
            self._send_json(public_status())
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
            billing = billing_status(auth, env=os.environ)
            usage = {}
            keys = {}
            try:
                usage = get_usage(auth, env=os.environ)
            except Exception as exc:  # noqa: BLE001
                usage = {"error": str(exc)}
            try:
                keys = list_keys(auth, env=os.environ)
            except Exception as exc:  # noqa: BLE001
                keys = {"error": str(exc)}
            self._send_json(
                {
                    "api_version": API_VERSION,
                    "authenticated": auth["authenticated"],
                    "auth_mode": auth["auth_mode"],
                    "api_key_fingerprint": auth.get("api_key_fingerprint"),
                    "workspace_id": auth.get("workspace_id"),
                    "workspace_name": auth.get("workspace_name"),
                    "subscription": auth["subscription"],
                    "billing": billing["billing"],
                    "manual_crypto": billing["manual_crypto"],
                    "usage": usage,
                    "keys": keys,
                }
            )
            return

        if path == "/v0/usage":
            try:
                auth = authenticate_headers(self.headers)
                self._send_json(get_usage(auth, env=os.environ))
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/v0/keys":
            try:
                auth = authenticate_headers(self.headers)
                self._send_json(list_keys(auth, env=os.environ))
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except KeyManageError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            return

        if path == "/v0/billing/status":
            try:
                auth = authenticate_headers(self.headers)
                result = billing_status(auth, env=os.environ)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            except BillingError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            self._send_json(result)
            return

        if path == "/v0/admin/workspaces":
            try:
                authenticate_admin_headers(self.headers)
            except AdminAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            query = parse_qs(parsed.query)
            limit = _safe_int((query.get("limit") or ["50"])[0], default=50)
            self._send_json(list_admin_workspaces(env=os.environ, limit=limit))
            return

        if path == "/v0/admin/billing-reviews":
            try:
                authenticate_admin_headers(self.headers)
            except AdminAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            query = parse_qs(parsed.query)
            limit = _safe_int((query.get("limit") or ["50"])[0], default=50)
            self._send_json(list_billing_reviews(env=os.environ, limit=limit))
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

        if path == "/v0/register":
            try:
                payload = self._read_json_body()
                result = register_workspace(payload)
            except (AccountError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result, status=HTTPStatus.CREATED)
            return

        if path == "/v0/verify":
            try:
                payload = self._read_json_body()
                token = str(payload.get("verification_token") or payload.get("token") or "")
                result = verify_registration(token)
            except (AccountError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result)
            return

        if path == "/v0/login":
            try:
                payload = self._read_json_body()
                result = login_with_password(payload)
            except (AccountError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result)
            return

        if path == "/v0/logout":
            try:
                auth_header = ""
                for key, value in self.headers.items():
                    if str(key).lower() == "authorization":
                        auth_header = str(value)
                        break
                token = ""
                if auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
                if not token:
                    payload = self._read_json_body() if int(self.headers.get("content-length") or 0) else {}
                    token = str((payload or {}).get("session_token") or (payload or {}).get("token") or "")
                result = logout_session(token)
            except (AccountError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result)
            return

        if path == "/v0/demo/check":
            try:
                payload = self._read_json_body()
                result = check_demo_answer(payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)
            return

        if path == "/v0/billing/manual-crypto-intent":
            try:
                auth = authenticate_headers(self.headers)
                payload = self._read_json_body()
                result = create_manual_crypto_intent(auth, payload, env=os.environ)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            except (BillingError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result, status=HTTPStatus.CREATED)
            return

        if path == "/v0/billing/submit-txid":
            try:
                auth = authenticate_headers(self.headers)
                payload = self._read_json_body()
                result = submit_manual_crypto_txid(auth, payload, env=os.environ)
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            except (BillingError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result)
            return

        if path.startswith("/v0/admin/workspaces/") and path.endswith("/activate"):
            try:
                admin_auth = authenticate_admin_headers(self.headers)
                payload = self._read_json_body()
                parts = path.strip("/").split("/")
                if len(parts) != 5:
                    raise AdminActionError("invalid admin activation path", status_code=HTTPStatus.NOT_FOUND)
                result = activate_workspace_after_manual_review(parts[3], payload, env=os.environ, admin_auth=admin_auth)
            except AdminAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
                return
            except (AdminActionError, TypeError, ValueError, json.JSONDecodeError) as exc:
                status = getattr(exc, "status_code", HTTPStatus.BAD_REQUEST)
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json(result)
            return

        if path == "/v0/keys/rotate":
            try:
                auth = authenticate_headers(self.headers)
                payload = self._read_json_body() if int(self.headers.get("content-length") or 0) else {}
                label = str((payload or {}).get("label") or "rotated")
                self._send_json(rotate_key(auth, env=os.environ, label=label))
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except KeyManageError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/v0/keys/revoke":
            try:
                auth = authenticate_headers(self.headers)
                payload = self._read_json_body()
                fingerprint = str(payload.get("fingerprint") or payload.get("api_key_fingerprint") or "")
                self._send_json(revoke_key(auth, fingerprint, env=os.environ))
            except ApiAuthError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except KeyManageError as exc:
                self._send_json({"error": str(exc)}, status=exc.status_code)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
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
        except RateLimitError as exc:
            self._send_json(
                {"error": str(exc), "retry_after": exc.retry_after},
                status=exc.status_code,
            )
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
        origin = self.headers.get("origin", "").strip()
        allowed_origin = _allowed_cors_origin(origin, env=os.environ)
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "authorization, x-api-key, x-admin-key, content-type")
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


def _allowed_cors_origin(origin: str, *, env: dict[str, str]) -> str | None:
    normalized = str(origin or "").strip().rstrip("/")
    if not normalized:
        return None
    raw = env.get("SEMEAI_GATE_CORS_ORIGINS") or env.get("SEMEAI_GATE_CORS_ORIGIN") or ""
    configured = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    defaults = {
        "https://semeai.tech",
        "https://www.semeai.tech",
        "https://gate.semeai.tech",
    }
    allowed = configured or defaults
    return normalized if normalized in allowed else None


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
