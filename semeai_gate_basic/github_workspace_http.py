"""HTTP routing adapter for the isolated repository workspace."""

from __future__ import annotations

import json
import os
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Any, Mapping
from urllib.parse import parse_qs

from .github_workspace import (
    OAUTH_BINDING_COOKIE,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    STATE_TTL_SECONDS,
    GitHubWorkspaceError,
    authenticate_session,
    begin_github_authorization,
    begin_github_installation,
    delete_benchmark_account,
    disconnect_installation,
    finish_github_authorization,
    finish_github_installation,
    get_benchmark_run,
    github_configuration,
    list_benchmark_runs,
    list_installations,
    list_repositories,
    public_site_origin,
    revoke_session,
    sync_repositories,
    workspace_overview,
)
from .repository_benchmark import analyzer_configuration, execute_repository_benchmark


def _cookies(headers: Mapping[str, str]) -> dict[str, str]:
    jar = SimpleCookie()
    jar.load(str(headers.get("Cookie") or headers.get("cookie") or ""))
    return {name: morsel.value for name, morsel in jar.items()}


def _cookie(name: str, value: str, *, max_age: int) -> str:
    return f"{name}={value}; Path=/v0; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax"


def _redirect(handler: Any, location: str, *, cookies: list[str] | None = None) -> None:
    handler.send_response(HTTPStatus.FOUND)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Content-Type-Options", "nosniff")
    for value in cookies or []:
        handler.send_header("Set-Cookie", value)
    handler.end_headers()


def _auth(handler: Any) -> dict[str, Any]:
    return authenticate_session(_cookies(handler.headers).get(SESSION_COOKIE, ""), env=os.environ)


def _require_frontend_origin(handler: Any) -> None:
    supplied = str(handler.headers.get("Origin") or "").strip().rstrip("/")
    expected = public_site_origin(env=os.environ)
    if supplied != expected:
        raise GitHubWorkspaceError("request origin is not allowed", status_code=403, code="csrf_origin")


def _query_value(query: Mapping[str, list[str]], key: str) -> str:
    return str((query.get(key) or [""])[0])


def _error(handler: Any, exc: Exception) -> None:
    status = int(getattr(exc, "status_code", HTTPStatus.BAD_REQUEST))
    code = str(getattr(exc, "code", "workspace_error"))
    _workspace_json(handler, {"error": str(exc), "code": code}, status=status)


def _workspace_json(
    handler: Any,
    payload: dict[str, Any],
    *,
    status: int | HTTPStatus = HTTPStatus.OK,
    cookies: list[str] | None = None,
) -> None:
    handler._send_json(
        payload,
        status=status,
        cookies=cookies,
        cache_control="no-store, private",
    )


def handle_workspace_get(handler: Any, path: str, query: Mapping[str, list[str]]) -> bool:
    if path == "/v0/oauth/github/start":
        try:
            result = begin_github_authorization(
                return_path=_query_value(query, "return_path") or "/benchmark/workspace/",
                env=os.environ,
            )
            _redirect(
                handler,
                result["authorize_url"],
                cookies=[_cookie(OAUTH_BINDING_COOKIE, result["browser_token"], max_age=STATE_TTL_SECONDS)],
            )
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/oauth/github/callback":
        cookies = _cookies(handler.headers)
        state = _query_value(query, "state")
        code = _query_value(query, "code")
        denied = bool(_query_value(query, "error"))
        try:
            result = finish_github_authorization(
                code="" if denied else code,
                state=state,
                browser_token=cookies.get(OAUTH_BINDING_COOKIE, ""),
                env=os.environ,
            )
            previous_session = cookies.get(SESSION_COOKIE, "")
            if previous_session:
                try:
                    revoke_session(previous_session, env=os.environ)
                except GitHubWorkspaceError:
                    pass
            destination = public_site_origin(env=os.environ) + result["return_path"]
            _redirect(
                handler,
                destination,
                cookies=[
                    _cookie(SESSION_COOKIE, result["session"]["session_token"], max_age=SESSION_TTL_SECONDS),
                    _cookie(OAUTH_BINDING_COOKIE, "", max_age=0),
                ],
            )
        except GitHubWorkspaceError as exc:
            if exc.code == "authorization_denied":
                _redirect(
                    handler,
                    public_site_origin(env=os.environ) + "/benchmark/workspace/?auth=denied",
                    cookies=[_cookie(OAUTH_BINDING_COOKIE, "", max_age=0)],
                )
            else:
                _error(handler, exc)
        return True

    if path == "/v0/me":
        try:
            _workspace_json(handler, workspace_overview(_auth(handler), env=os.environ))
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/github/install/start":
        try:
            result = begin_github_installation(_auth(handler), env=os.environ)
            _redirect(handler, result["install_url"])
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/github/install/callback":
        try:
            finish_github_installation(
                installation_id=_query_value(query, "installation_id"),
                state=_query_value(query, "state"),
                auth=_auth(handler),
                env=os.environ,
            )
            _redirect(handler, public_site_origin(env=os.environ) + "/benchmark/workspace/?installation=connected")
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/github/installations":
        try:
            _workspace_json(handler, {"installations": list_installations(_auth(handler), env=os.environ)})
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/github/repositories":
        try:
            _workspace_json(handler, {"repositories": list_repositories(_auth(handler), env=os.environ)})
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/benchmark/runs":
        try:
            repository_id = _query_value(query, "repository_id")
            _workspace_json(
                handler,
                {
                    "runs": list_benchmark_runs(
                        _auth(handler),
                        repository_id=int(repository_id) if repository_id else None,
                        env=os.environ,
                    )
                }
            )
        except (GitHubWorkspaceError, ValueError) as exc:
            _error(handler, exc)
        return True

    run_match = re.fullmatch(r"/v0/benchmark/runs/(run_[0-9a-f]{24})", path)
    if run_match:
        try:
            _workspace_json(handler, get_benchmark_run(_auth(handler), run_match.group(1), env=os.environ))
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    if path == "/v0/benchmark/configuration":
        _workspace_json(
            handler,
            {
                "github": github_configuration(env=os.environ),
                "analyzer": analyzer_configuration(env=os.environ),
            },
        )
        return True

    return False


def handle_workspace_post(handler: Any, path: str) -> bool:
    if path == "/v0/oauth/github/logout":
        try:
            _require_frontend_origin(handler)
            token = _cookies(handler.headers).get(SESSION_COOKIE, "")
            result = revoke_session(token, env=os.environ)
            _workspace_json(handler, result, cookies=[_cookie(SESSION_COOKIE, "", max_age=0)])
        except GitHubWorkspaceError as exc:
            _error(handler, exc)
        return True

    disconnect_match = re.fullmatch(r"/v0/github/installations/(\d+)/disconnect", path)
    if disconnect_match:
        try:
            _require_frontend_origin(handler)
            handler._read_json_body()
            _workspace_json(
                handler,
                disconnect_installation(_auth(handler), int(disconnect_match.group(1)), env=os.environ)
            )
        except (GitHubWorkspaceError, ValueError) as exc:
            _error(handler, exc)
        return True

    if path == "/v0/github/repositories/refresh":
        try:
            _require_frontend_origin(handler)
            payload = handler._read_json_body()
            auth = _auth(handler)
            installation_id = payload.get("installation_id")
            if installation_id is not None:
                repositories = sync_repositories(auth, int(installation_id), env=os.environ)
            else:
                active = [
                    item
                    for item in list_installations(auth, env=os.environ)
                    if item.get("status") == "active"
                ]
                repositories = []
                for installation in active:
                    repositories.extend(
                        sync_repositories(auth, int(installation["installation_id"]), env=os.environ)
                    )
            _workspace_json(handler, {"repositories": repositories})
        except (GitHubWorkspaceError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _error(handler, exc)
        return True

    if path == "/v0/benchmark/runs":
        try:
            _require_frontend_origin(handler)
            payload = handler._read_json_body()
            repository_id = int(payload.get("repository_id"))
            result = execute_repository_benchmark(_auth(handler), repository_id, env=os.environ)
            _workspace_json(handler, result, status=HTTPStatus.CREATED)
        except (GitHubWorkspaceError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _error(handler, exc)
        return True

    if path == "/v0/benchmark/account/delete":
        try:
            _require_frontend_origin(handler)
            payload = handler._read_json_body()
            if payload.get("confirmation") != "DELETE BENCHMARK ACCOUNT":
                raise GitHubWorkspaceError("explicit account deletion confirmation is required", status_code=400)
            result = delete_benchmark_account(_auth(handler), env=os.environ)
            _workspace_json(handler, result, cookies=[_cookie(SESSION_COOKIE, "", max_age=0)])
        except (GitHubWorkspaceError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _error(handler, exc)
        return True

    return False
