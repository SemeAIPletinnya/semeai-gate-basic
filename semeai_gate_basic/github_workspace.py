"""GitHub App identity, installation, and durable repository-workspace records.

The benchmark workspace is deliberately separate from the existing Gate SaaS
account model. GitHub numeric user IDs are its immutable identity key; email is
never used to merge account methods.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


DEFAULT_WORKSPACE_ROOT = Path("outputs") / "repository_workspace"
SESSION_COOKIE = "semeai_benchmark_session"
OAUTH_BINDING_COOKIE = "semeai_benchmark_oauth"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
STATE_TTL_SECONDS = 10 * 60
RETURN_PATHS = {"/benchmark/workspace/", "/benchmark/"}
GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_LOCK = threading.RLock()


class GitHubWorkspaceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "workspace_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubWorkspaceError("stored timestamp is invalid", status_code=500) from exc


def workspace_root(*, env: Mapping[str, str] | None = None) -> Path:
    values = env or os.environ
    explicit = str(values.get("SEMEAI_BENCHMARK_WORKSPACE_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    account_root = str(values.get("SEMEAI_GATE_ACCOUNT_DIR") or "").strip()
    return (Path(account_root) / "benchmark_workspace") if account_root else DEFAULT_WORKSPACE_ROOT


def _ensure_dirs(root: Path) -> None:
    for name in ("users", "sessions", "states", "installations", "repositories", "runs"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _session_secret(env: Mapping[str, str]) -> bytes:
    value = str(env.get("SEMEAI_SESSION_COOKIE_SECRET") or "")
    if len(value) < 32:
        raise GitHubWorkspaceError("benchmark workspace session security is not configured", status_code=503)
    return value.encode("utf-8")


def _digest(value: str, *, purpose: str, env: Mapping[str, str]) -> str:
    return hmac.new(_session_secret(env), f"{purpose}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _safe_return_path(value: str | None) -> str:
    candidate = str(value or "/benchmark/workspace/").strip()
    if candidate not in RETURN_PATHS:
        raise GitHubWorkspaceError("return path is not allowed", status_code=400, code="invalid_return_path")
    return candidate


def public_site_origin(*, env: Mapping[str, str] | None = None) -> str:
    values = env or os.environ
    raw = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL") or "https://semeai.tech").strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise GitHubWorkspaceError("public site URL is invalid", status_code=503)
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise GitHubWorkspaceError("public site URL must use HTTPS", status_code=503)
    return f"{parsed.scheme}://{parsed.netloc}"


def _validated_callback(name: str, expected_path: str, env: Mapping[str, str]) -> str:
    raw = str(env.get(name) or "").strip()
    if not raw:
        raise GitHubWorkspaceError(f"{name} is not configured", status_code=503)
    parsed = urllib.parse.urlparse(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != expected_path.rstrip("/")
    ):
        raise GitHubWorkspaceError(f"{name} must exactly identify {expected_path}", status_code=503)
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise GitHubWorkspaceError(f"{name} must use HTTPS outside local development", status_code=503)
    return raw


def github_configuration(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    private_key_path = str(values.get("SEMEAI_GITHUB_PRIVATE_KEY_PATH") or "").strip()
    return {
        "enabled": bool(
            values.get("SEMEAI_GITHUB_CLIENT_ID")
            and values.get("SEMEAI_GITHUB_CLIENT_SECRET")
            and values.get("SEMEAI_GITHUB_CALLBACK_URL")
            and values.get("SEMEAI_SESSION_COOKIE_SECRET")
            and values.get("SEMEAI_GATE_PUBLIC_SITE_URL")
        ),
        "app_configured": bool(
            values.get("SEMEAI_GITHUB_APP_ID")
            and values.get("SEMEAI_GITHUB_APP_SLUG")
            and values.get("SEMEAI_GITHUB_SETUP_URL")
            and private_key_path
            and Path(private_key_path).is_file()
        ),
        "start_path": "/v0/oauth/github/start",
        "callback_path": "/v0/oauth/github/callback",
        "install_start_path": "/v0/github/install/start",
        "install_callback_path": "/v0/github/install/callback",
        "repository_permissions": {"metadata": "read", "contents": "read"},
    }


def _create_state(
    *,
    kind: str,
    binding_hash: str,
    return_path: str,
    env: Mapping[str, str],
    user_id: str | None = None,
    now: datetime | None = None,
) -> str:
    root = workspace_root(env=env)
    _ensure_dirs(root)
    current = now or _now()
    raw = secrets.token_urlsafe(32)
    state_hash = _digest(raw, purpose="github-state", env=env)
    record = {
        "schema_version": "semeai.github-state.v1",
        "state_hash": state_hash,
        "kind": kind,
        "binding_hash": binding_hash,
        "user_id": user_id,
        "return_path": _safe_return_path(return_path),
        "created_at": _iso(current),
        "expires_at": _iso(current + timedelta(seconds=STATE_TTL_SECONDS)),
        "used_at": None,
    }
    with _LOCK:
        _atomic_json(root / "states" / f"{state_hash}.json", record)
    return raw


def consume_state(
    raw_state: str,
    *,
    kind: str,
    binding_hash: str,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    supplied = str(raw_state or "").strip()
    if not supplied:
        raise GitHubWorkspaceError("missing GitHub authorization state", status_code=400, code="missing_state")
    state_hash = _digest(supplied, purpose="github-state", env=values)
    path = workspace_root(env=values) / "states" / f"{state_hash}.json"
    with _LOCK:
        record = _load_json(path)
        if record is None or not hmac.compare_digest(str(record.get("state_hash") or ""), state_hash):
            raise GitHubWorkspaceError("invalid GitHub authorization state", status_code=400, code="invalid_state")
        if record.get("kind") != kind or not hmac.compare_digest(str(record.get("binding_hash") or ""), binding_hash):
            raise GitHubWorkspaceError("GitHub authorization state is not bound to this session", status_code=400, code="invalid_state")
        if record.get("used_at"):
            raise GitHubWorkspaceError("GitHub authorization state was already used", status_code=400, code="reused_state")
        if _parse_iso(str(record.get("expires_at") or "")) <= (now or _now()):
            raise GitHubWorkspaceError("GitHub authorization state expired", status_code=400, code="expired_state")
        record["used_at"] = _iso(now or _now())
        _atomic_json(path, record)
    return record


def begin_github_authorization(
    *, return_path: str = "/benchmark/workspace/", env: Mapping[str, str] | None = None
) -> dict[str, str]:
    values = env or os.environ
    client_id = str(values.get("SEMEAI_GITHUB_CLIENT_ID") or "").strip()
    if not client_id or not values.get("SEMEAI_GITHUB_CLIENT_SECRET"):
        raise GitHubWorkspaceError("GitHub authorization is not configured", status_code=503)
    callback = _validated_callback("SEMEAI_GITHUB_CALLBACK_URL", "/v0/oauth/github/callback", values)
    browser_token = secrets.token_urlsafe(32)
    binding_hash = _digest(browser_token, purpose="oauth-browser", env=values)
    state = _create_state(
        kind="authorization",
        binding_hash=binding_hash,
        return_path=_safe_return_path(return_path),
        env=values,
    )
    query = urllib.parse.urlencode(
        {"client_id": client_id, "redirect_uri": callback, "state": state, "allow_signup": "true"}
    )
    return {
        "authorize_url": f"https://github.com/login/oauth/authorize?{query}",
        "browser_token": browser_token,
        "state": state,
    }


GitHubRequester = Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _validate_github_request_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    valid = (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and (
            (parsed.hostname == "github.com" and parsed.path == "/login/oauth/access_token")
            or (parsed.hostname == "api.github.com" and parsed.path.startswith("/"))
        )
    )
    if not valid:
        raise GitHubWorkspaceError("refused unsafe GitHub request URL", status_code=500)


def _request_json(
    url: str,
    method: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any] | None,
) -> dict[str, Any]:
    _validate_github_request_url(url)
    data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
    request_headers = {**dict(headers), "User-Agent": "SemeAI-Repository-Workspace/1.0"}
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise GitHubWorkspaceError("GitHub authorization request failed", status_code=502, code="github_exchange_failed") from exc
    if len(raw) > 1024 * 1024:
        raise GitHubWorkspaceError("GitHub returned an oversized response", status_code=502)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubWorkspaceError("GitHub returned an unreadable response", status_code=502) from exc
    if not isinstance(payload, dict):
        raise GitHubWorkspaceError("GitHub returned an invalid response", status_code=502)
    return payload


def normalize_github_identity(profile: Mapping[str, Any]) -> dict[str, Any]:
    try:
        github_user_id = int(profile.get("id"))
    except (TypeError, ValueError) as exc:
        raise GitHubWorkspaceError("GitHub identity is missing its immutable numeric id", status_code=502) from exc
    login = str(profile.get("login") or "").strip()
    if github_user_id <= 0 or not GITHUB_LOGIN_RE.fullmatch(login):
        raise GitHubWorkspaceError("GitHub returned an invalid user identity", status_code=502)
    avatar = str(profile.get("avatar_url") or "").strip()
    parsed_avatar = urllib.parse.urlparse(avatar)
    if parsed_avatar.scheme != "https" or parsed_avatar.hostname != "avatars.githubusercontent.com":
        avatar = ""
    name = str(profile.get("name") or "").strip()[:160]
    return {
        "github_user_id": github_user_id,
        "github_login": login,
        "avatar_url": avatar,
        "display_name": name,
    }


def _user_path(root: Path, user_id: str) -> Path:
    return root / "users" / f"{user_id}.json"


def _find_user_by_github_id(root: Path, github_user_id: int) -> tuple[Path, dict[str, Any]] | None:
    for path in (root / "users").glob("usr_*.json"):
        user = _load_json(path)
        if user and int(user.get("github_user_id") or 0) == github_user_id:
            return path, user
    return None


def upsert_github_user(
    profile: Mapping[str, Any], *, env: Mapping[str, str] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    values = env or os.environ
    identity = normalize_github_identity(profile)
    root = workspace_root(env=values)
    _ensure_dirs(root)
    current = now or _now()
    with _LOCK:
        existing = _find_user_by_github_id(root, identity["github_user_id"])
        if existing:
            path, user = existing
            user.update(identity)
            user["last_login_at"] = _iso(current)
            _atomic_json(path, user)
            return user
        user = {
            "schema_version": "semeai.repository-workspace-user.v1",
            "user_id": "usr_" + secrets.token_hex(12),
            **identity,
            "created_at": _iso(current),
            "last_login_at": _iso(current),
        }
        _atomic_json(_user_path(root, user["user_id"]), user)
        return user


def create_session(
    user_id: str, *, env: Mapping[str, str] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    values = env or os.environ
    root = workspace_root(env=values)
    _ensure_dirs(root)
    current = now or _now()
    raw = "semeai_bws_" + secrets.token_urlsafe(32)
    session_hash = _digest(raw, purpose="benchmark-session", env=values)
    record = {
        "schema_version": "semeai.repository-workspace-session.v1",
        "session_id_hash": session_hash,
        "user_id": user_id,
        "created_at": _iso(current),
        "expires_at": _iso(current + timedelta(seconds=SESSION_TTL_SECONDS)),
        "revoked_at": None,
    }
    with _LOCK:
        _atomic_json(root / "sessions" / f"{session_hash}.json", record)
    return {"session_token": raw, **record}


def authenticate_session(
    raw_token: str, *, env: Mapping[str, str] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    values = env or os.environ
    token = str(raw_token or "").strip()
    if not token:
        raise GitHubWorkspaceError("authentication required", status_code=401, code="unauthenticated")
    root = workspace_root(env=values)
    session_hash = _digest(token, purpose="benchmark-session", env=values)
    session = _load_json(root / "sessions" / f"{session_hash}.json")
    if session is None or not hmac.compare_digest(str(session.get("session_id_hash") or ""), session_hash):
        raise GitHubWorkspaceError("authentication required", status_code=401, code="unauthenticated")
    if session.get("revoked_at"):
        raise GitHubWorkspaceError("session is revoked", status_code=401, code="unauthenticated")
    if _parse_iso(str(session.get("expires_at") or "")) <= (now or _now()):
        raise GitHubWorkspaceError("session expired", status_code=401, code="session_expired")
    user = _load_json(_user_path(root, str(session.get("user_id") or "")))
    if user is None:
        raise GitHubWorkspaceError("account no longer exists", status_code=401, code="unauthenticated")
    return {"session": session, "user": user, "session_hash": session_hash}


def revoke_session(raw_token: str, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    auth = authenticate_session(raw_token, env=values)
    root = workspace_root(env=values)
    session = auth["session"]
    session["revoked_at"] = _iso(_now())
    with _LOCK:
        _atomic_json(root / "sessions" / f"{auth['session_hash']}.json", session)
    return {"status": "logged_out"}


def finish_github_authorization(
    *,
    code: str,
    state: str,
    browser_token: str,
    env: Mapping[str, str] | None = None,
    request_json: GitHubRequester | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    callback = _validated_callback("SEMEAI_GITHUB_CALLBACK_URL", "/v0/oauth/github/callback", values)
    binding_hash = _digest(str(browser_token or ""), purpose="oauth-browser", env=values)
    state_record = consume_state(
        state,
        kind="authorization",
        binding_hash=binding_hash,
        env=values,
        now=now,
    )
    if not str(code or "").strip():
        raise GitHubWorkspaceError("GitHub authorization was denied", status_code=400, code="authorization_denied")
    requester = request_json or _request_json
    token_payload = requester(
        "https://github.com/login/oauth/access_token",
        "POST",
        {"Accept": "application/json", "Content-Type": "application/json"},
        {
            "client_id": str(values.get("SEMEAI_GITHUB_CLIENT_ID") or ""),
            "client_secret": str(values.get("SEMEAI_GITHUB_CLIENT_SECRET") or ""),
            "code": str(code),
            "redirect_uri": callback,
        },
    )
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise GitHubWorkspaceError("GitHub authorization failed", status_code=502, code="github_exchange_failed")
    profile = requester(
        "https://api.github.com/user",
        "GET",
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        None,
    )
    user = upsert_github_user(profile, env=values, now=now)
    session = create_session(user["user_id"], env=values, now=now)
    return {"user": user, "session": session, "return_path": state_record["return_path"]}


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_github_app_jwt(*, env: Mapping[str, str] | None = None, now: datetime | None = None) -> str:
    values = env or os.environ
    app_id = str(values.get("SEMEAI_GITHUB_APP_ID") or "").strip()
    key_path = Path(str(values.get("SEMEAI_GITHUB_PRIVATE_KEY_PATH") or "").strip())
    if not app_id or not key_path.is_file():
        raise GitHubWorkspaceError("GitHub App signing credentials are not configured", status_code=503)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:
        raise GitHubWorkspaceError("GitHub App signing support is unavailable", status_code=503) from exc
    current = int((now or _now()).timestamp())
    header = _base64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _base64url(json.dumps({"iat": current - 30, "exp": current + 540, "iss": app_id}, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except (OSError, ValueError, TypeError) as exc:
        raise GitHubWorkspaceError("GitHub App private key could not be loaded", status_code=503) from exc
    return f"{header}.{payload}.{_base64url(signature)}"


def _app_headers(env: Mapping[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {create_github_app_jwt(env=env)}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def begin_github_installation(
    auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    values = env or os.environ
    slug = str(values.get("SEMEAI_GITHUB_APP_SLUG") or "").strip()
    if not slug or not re.fullmatch(r"[A-Za-z0-9-]+", slug):
        raise GitHubWorkspaceError("GitHub App slug is not configured", status_code=503)
    _validated_callback("SEMEAI_GITHUB_SETUP_URL", "/v0/github/install/callback", values)
    session_hash = str(auth.get("session_hash") or "")
    state = _create_state(
        kind="installation",
        binding_hash=session_hash,
        user_id=str(auth["user"]["user_id"]),
        return_path="/benchmark/workspace/",
        env=values,
    )
    return {
        "install_url": f"https://github.com/apps/{urllib.parse.quote(slug)}/installations/new?{urllib.parse.urlencode({'state': state})}",
        "state": state,
    }


def finish_github_installation(
    *,
    installation_id: str,
    state: str,
    auth: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    request_json: GitHubRequester | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    _validated_callback("SEMEAI_GITHUB_SETUP_URL", "/v0/github/install/callback", values)
    state_record = consume_state(
        state,
        kind="installation",
        binding_hash=str(auth.get("session_hash") or ""),
        env=values,
    )
    if state_record.get("user_id") != auth["user"].get("user_id"):
        raise GitHubWorkspaceError("installation state belongs to another account", status_code=403)
    try:
        numeric_id = int(installation_id)
    except (TypeError, ValueError) as exc:
        raise GitHubWorkspaceError("installation id is invalid", status_code=400) from exc
    if numeric_id <= 0:
        raise GitHubWorkspaceError("installation id is invalid", status_code=400)
    requester = request_json or _request_json
    installation = requester(
        f"https://api.github.com/app/installations/{numeric_id}", "GET", _app_headers(values), None
    )
    if int(installation.get("id") or 0) != numeric_id:
        raise GitHubWorkspaceError("GitHub returned an unexpected installation", status_code=502)
    account = installation.get("account") if isinstance(installation.get("account"), dict) else {}
    try:
        account_id = int(account.get("id"))
    except (TypeError, ValueError) as exc:
        raise GitHubWorkspaceError("GitHub installation account is invalid", status_code=502) from exc
    if account_id <= 0:
        raise GitHubWorkspaceError("GitHub installation account is invalid", status_code=502)
    record = {
        "schema_version": "semeai.github-installation.v1",
        "installation_id": numeric_id,
        "user_id": auth["user"]["user_id"],
        "github_account_id": account_id,
        "github_account_login": str(account.get("login") or "")[:100],
        "status": "suspended" if installation.get("suspended_at") else "active",
        "created_at": _iso(_now()),
    }
    root = workspace_root(env=values)
    _ensure_dirs(root)
    with _LOCK:
        existing = _load_json(root / "installations" / f"{numeric_id}.json")
        if existing and existing.get("user_id") != auth["user"]["user_id"]:
            raise GitHubWorkspaceError("installation is already linked to another account", status_code=409)
        if existing:
            record["created_at"] = existing.get("created_at") or record["created_at"]
        _atomic_json(root / "installations" / f"{numeric_id}.json", record)
    return record


def list_installations(auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    root = workspace_root(env=env or os.environ)
    user_id = auth["user"]["user_id"]
    records = []
    for path in (root / "installations").glob("*.json"):
        record = _load_json(path)
        if record and record.get("user_id") == user_id:
            records.append(record)
    return sorted(records, key=lambda item: int(item["installation_id"]))


def _owned_installation(auth: Mapping[str, Any], installation_id: int, env: Mapping[str, str]) -> dict[str, Any]:
    record = _load_json(workspace_root(env=env) / "installations" / f"{installation_id}.json")
    if record is None or record.get("user_id") != auth["user"].get("user_id"):
        raise GitHubWorkspaceError("installation not found", status_code=404)
    if record.get("status") != "active":
        raise GitHubWorkspaceError("installation is not active", status_code=409)
    return record


def create_installation_access_token(
    installation_id: int,
    *,
    env: Mapping[str, str] | None = None,
    request_json: GitHubRequester | None = None,
) -> str:
    values = env or os.environ
    if int(installation_id) <= 0:
        raise GitHubWorkspaceError("installation id is invalid", status_code=400)
    requester = request_json or _request_json
    payload = requester(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        "POST",
        _app_headers(values),
        {"permissions": {"contents": "read", "metadata": "read"}},
    )
    token = str(payload.get("token") or "").strip()
    if not token:
        raise GitHubWorkspaceError("GitHub did not issue an installation token", status_code=502)
    return token


def sync_repositories(
    auth: Mapping[str, Any],
    installation_id: int,
    *,
    env: Mapping[str, str] | None = None,
    request_json: GitHubRequester | None = None,
) -> list[dict[str, Any]]:
    values = env or os.environ
    installation = _owned_installation(auth, int(installation_id), values)
    requester = request_json or _request_json
    token = create_installation_access_token(int(installation_id), env=values, request_json=requester)
    response = requester(
        "https://api.github.com/installation/repositories?per_page=100",
        "GET",
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        None,
    )
    repositories = response.get("repositories") if isinstance(response.get("repositories"), list) else []
    if int(response.get("total_count") or len(repositories)) > 100:
        raise GitHubWorkspaceError("installation exposes more than the bounded 100-repository limit", status_code=409)
    root = workspace_root(env=values)
    _ensure_dirs(root)
    now = _iso(_now())
    output = []
    for item in repositories:
        if not isinstance(item, dict):
            continue
        try:
            repository_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        full_name = str(item.get("full_name") or "")
        if repository_id <= 0 or "/" not in full_name or len(full_name) > 220:
            continue
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        record = {
            "schema_version": "semeai.connected-repository.v1",
            "github_repository_id": repository_id,
            "installation_id": installation["installation_id"],
            "user_id": auth["user"]["user_id"],
            "full_name": full_name,
            "owner": str(owner.get("login") or full_name.split("/", 1)[0]),
            "private": bool(item.get("private")),
            "default_branch": str(item.get("default_branch") or "")[:255],
            "connection_status": "active",
            "last_synchronized_at": now,
        }
        output.append(record)
    active_ids = {int(record["github_repository_id"]) for record in output}
    with _LOCK:
        for path in (root / "repositories").glob(f"{auth['user']['user_id']}_*.json"):
            existing = _load_json(path)
            if (
                existing
                and int(existing.get("installation_id") or 0) == int(installation_id)
                and int(existing.get("github_repository_id") or 0) not in active_ids
            ):
                existing["connection_status"] = "disconnected"
                existing["last_synchronized_at"] = now
                _atomic_json(path, existing)
        for record in output:
            _atomic_json(
                root / "repositories" / f"{record['user_id']}_{record['github_repository_id']}.json",
                record,
            )
    return sorted(output, key=lambda item: item["full_name"].lower())


def list_repositories(auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    root = workspace_root(env=env or os.environ)
    user_id = auth["user"]["user_id"]
    output = []
    for path in (root / "repositories").glob(f"{user_id}_*.json"):
        record = _load_json(path)
        if record and record.get("user_id") == user_id:
            output.append(record)
    return sorted(output, key=lambda item: str(item.get("full_name") or "").lower())


def get_owned_repository(
    auth: Mapping[str, Any], repository_id: int, *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    root = workspace_root(env=env or os.environ)
    user_id = auth["user"]["user_id"]
    record = _load_json(root / "repositories" / f"{user_id}_{int(repository_id)}.json")
    if record is None or record.get("user_id") != user_id or record.get("connection_status") != "active":
        raise GitHubWorkspaceError("connected repository not found", status_code=404)
    _owned_installation(auth, int(record["installation_id"]), env or os.environ)
    return record


def disconnect_installation(
    auth: Mapping[str, Any], installation_id: int, *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    values = env or os.environ
    root = workspace_root(env=values)
    record = _owned_installation(auth, int(installation_id), values)
    record["status"] = "disconnected"
    record["disconnected_at"] = _iso(_now())
    changed = 0
    with _LOCK:
        _atomic_json(root / "installations" / f"{installation_id}.json", record)
        for path in (root / "repositories").glob(f"{auth['user']['user_id']}_*.json"):
            repository = _load_json(path)
            if repository and int(repository.get("installation_id") or 0) == int(installation_id):
                repository["connection_status"] = "disconnected"
                _atomic_json(path, repository)
                changed += 1
    return {"status": "disconnected", "installation_id": int(installation_id), "repositories_disconnected": changed, "history_preserved": True}


def save_benchmark_run(
    auth: Mapping[str, Any], repository: Mapping[str, Any], result: Mapping[str, Any], *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    values = env or os.environ
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    snapshot = candidate.get("snapshot") if isinstance(candidate.get("snapshot"), dict) else {}
    receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    if str(snapshot.get("repository") or "").lower() != str(repository.get("full_name") or "").lower():
        raise GitHubWorkspaceError("benchmark result repository mismatch", status_code=500)
    claimed_hash = str(receipt.get("receipt_hash") or "")
    hash_payload = dict(receipt)
    hash_payload.pop("receipt_hash", None)
    canonical = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not claimed_hash or not hmac.compare_digest(claimed_hash, actual_hash):
        raise GitHubWorkspaceError("benchmark receipt integrity check failed", status_code=500)
    run_id = "run_" + secrets.token_hex(12)
    record = {
        "schema_version": "semeai.repository-workspace-run.v1",
        "run_id": run_id,
        "user_id": auth["user"]["user_id"],
        "github_repository_id": int(repository["github_repository_id"]),
        "repository": repository["full_name"],
        "private": bool(repository.get("private")),
        "source_commit": snapshot.get("commit_sha"),
        "source_timestamp": snapshot.get("captured_at"),
        "source_mode": snapshot.get("source_mode"),
        "analyzer_version": receipt.get("analyzer_version"),
        "scoring_policy_version": receipt.get("scoring_policy_version"),
        "analyzer_source_sha256": result.get("analyzer_source_sha256"),
        "total_score": candidate.get("totalScore"),
        "category_scores": receipt.get("category_scores") or [],
        "indicators": result.get("indicators") or {},
        "presentation_gate_decision": gate.get("decision"),
        "visual_seed": result.get("visual", {}).get("visualSeed"),
        "visual_phase": result.get("visual", {}).get("visualPhase"),
        "receipt_hash": claimed_hash,
        "normalized_evidence_result": snapshot.get("normalized_evidence") or {},
        "admitted_signals": receipt.get("admitted_signals") or [],
        "missing_signals": receipt.get("missing_signals") or [],
        "receipt": receipt,
        "created_at": _iso(_now()),
    }
    root = workspace_root(env=values)
    _ensure_dirs(root)
    with _LOCK:
        _atomic_json(root / "runs" / f"{run_id}.json", record)
    return record


def list_benchmark_runs(
    auth: Mapping[str, Any], *, repository_id: int | None = None, env: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    root = workspace_root(env=env or os.environ)
    user_id = auth["user"]["user_id"]
    records = []
    for path in (root / "runs").glob("run_*.json"):
        item = _load_json(path)
        if not item or item.get("user_id") != user_id:
            continue
        if repository_id is not None and int(item.get("github_repository_id") or 0) != int(repository_id):
            continue
        records.append(item)
    records.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("run_id") or "")))
    previous_by_repository: dict[int, dict[str, Any]] = {}
    summaries = []
    for item in records:
        repo_id = int(item["github_repository_id"])
        previous = previous_by_repository.get(repo_id)
        previous_scores = {entry["key"]: int(entry["score"]) for entry in (previous or {}).get("category_scores", [])}
        category_deltas = (
            {
                entry["key"]: int(entry["score"]) - int(previous_scores.get(entry["key"], 0))
                for entry in item.get("category_scores", [])
            }
            if previous
            else {}
        )
        current_evidence = {key for key, paths in item.get("normalized_evidence_result", {}).items() if paths}
        prior_evidence = {key for key, paths in (previous or {}).get("normalized_evidence_result", {}).items() if paths}
        summary = {key: value for key, value in item.items() if key not in {"receipt", "normalized_evidence_result", "admitted_signals", "missing_signals"}}
        summary.update(
            {
                "score_delta": None if previous is None else int(item["total_score"]) - int(previous["total_score"]),
                "category_deltas": category_deltas,
                "newly_admitted_evidence": sorted(current_evidence - prior_evidence) if previous else [],
                "no_longer_admitted_evidence": sorted(prior_evidence - current_evidence) if previous else [],
            }
        )
        summaries.append(summary)
        previous_by_repository[repo_id] = item
    return list(reversed(summaries))


def get_benchmark_run(
    auth: Mapping[str, Any], run_id: str, *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    if not re.fullmatch(r"run_[0-9a-f]{24}", str(run_id or "")):
        raise GitHubWorkspaceError("benchmark run not found", status_code=404)
    record = _load_json(workspace_root(env=env or os.environ) / "runs" / f"{run_id}.json")
    if record is None or record.get("user_id") != auth["user"].get("user_id"):
        raise GitHubWorkspaceError("benchmark run not found", status_code=404)
    return record


def workspace_overview(auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    installations = list_installations(auth, env=env)
    repositories = list_repositories(auth, env=env)
    runs = list_benchmark_runs(auth, env=env)
    return {
        "authenticated": True,
        "user": auth["user"],
        "counts": {
            "installations": len([item for item in installations if item.get("status") == "active"]),
            "connected_repositories": len([item for item in repositories if item.get("connection_status") == "active"]),
            "benchmark_runs": len(runs),
        },
        "latest_gate": runs[0].get("presentation_gate_decision") if runs else None,
    }


def delete_benchmark_account(auth: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    root = workspace_root(env=values)
    user_id = auth["user"]["user_id"]
    counts = {"sessions": 0, "installations": 0, "repositories": 0, "runs": 0, "states": 0, "users": 0}
    patterns = {
        "sessions": (root / "sessions", "*.json"),
        "installations": (root / "installations", "*.json"),
        "repositories": (root / "repositories", f"{user_id}_*.json"),
        "runs": (root / "runs", "run_*.json"),
        "states": (root / "states", "*.json"),
    }
    with _LOCK:
        for key, (directory, pattern) in patterns.items():
            for path in directory.glob(pattern):
                record = _load_json(path)
                if record and record.get("user_id") == user_id:
                    path.unlink(missing_ok=True)
                    counts[key] += 1
        user_path = _user_path(root, user_id)
        if user_path.exists():
            user_path.unlink()
            counts["users"] = 1
    return {"status": "deleted", "deleted": counts}
