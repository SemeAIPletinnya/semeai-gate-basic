"""Bounded GitHub evidence capture plus execution of the canonical JS analyzer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .github_workspace import (
    GitHubWorkspaceError,
    create_installation_access_token,
    get_owned_repository,
    save_benchmark_run,
)


MAX_TREE_ENTRIES = 10_000
MAX_TREE_BYTES = 4 * 1024 * 1024
MAX_README_BYTES = 64 * 1024
MAX_DOCUMENT_BYTES = 48 * 1024
MAX_JSON_BYTES = 512 * 1024
SELECTED_DOCUMENT_PATHS = (
    "docs/runtime_decision_contract.md",
    "docs/review_release_receipt_layer.md",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise GitHubWorkspaceError("GitHub returned an unexpected redirect", status_code=502)


def _github_fetch(
    url: str,
    token: str,
    accept: str,
    max_bytes: int,
    text_response: bool,
) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.username or parsed.password:
        raise GitHubWorkspaceError("refused unsafe GitHub API URL", status_code=500)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SemeAI-Repository-Workspace/1.0",
        },
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GitHubWorkspaceError("GitHub evidence was not found", status_code=404, code="not_found") from exc
        if exc.code == 403:
            raise GitHubWorkspaceError("GitHub denied installation access", status_code=403, code="inaccessible") from exc
        raise GitHubWorkspaceError("GitHub evidence request failed", status_code=502, code="github_error") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GitHubWorkspaceError("GitHub evidence request failed", status_code=502, code="github_error") from exc
    if len(raw) > max_bytes:
        raise GitHubWorkspaceError("GitHub evidence response exceeded its safety limit", status_code=413)
    decoded = raw.decode("utf-8", errors="replace")
    if text_response:
        return decoded
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise GitHubWorkspaceError("GitHub returned unreadable evidence", status_code=502) from exc


GitHubFetcher = Callable[[str, str, str, int, bool], Any]


def analyzer_configuration(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Report whether the canonical analyzer can execute without exposing operator paths."""

    values = env or os.environ
    configured_path = str(values.get("SEMEAI_BENCHMARK_CORE_PATH") or "").strip()
    core_path = Path(configured_path).resolve() if configured_path else None
    source_hash = hashlib.sha256(core_path.read_bytes()).hexdigest() if core_path and core_path.is_file() else ""
    expected_hash = str(values.get("SEMEAI_BENCHMARK_CORE_SHA256") or "").strip().lower()
    node_binary = str(values.get("SEMEAI_NODE_BINARY") or "node").strip()
    runner = Path(__file__).with_name("repository_benchmark_runner.js")
    return {
        "configured": bool(
            core_path
            and core_path.is_file()
            and core_path.name == "benchmark.js"
            and runner.is_file()
            and shutil.which(node_binary)
            and (not expected_hash or hmac_compare(source_hash, expected_hash))
        ),
        "source_sha256": source_hash if source_hash and (not expected_hash or hmac_compare(source_hash, expected_hash)) else None,
        "policy_execution": "canonical-js-core",
    }


def _optional(fetcher: GitHubFetcher, *args: Any) -> Any:
    try:
        return fetcher(*args)
    except GitHubWorkspaceError as exc:
        if exc.code == "not_found":
            return None
        raise


def _api_url(full_name: str, suffix: str) -> str:
    owner, repository = full_name.split("/", 1)
    return (
        "https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repository, safe='')}{suffix}"
    )


def _content_path(value: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in value.split("/"))


def _captured_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def collect_authorized_snapshot(
    repository: Mapping[str, Any],
    installation_token: str,
    *,
    fetcher: GitHubFetcher | None = None,
) -> dict[str, Any]:
    """Capture only the bounded metadata/path/document signals used by the canonical analyzer."""

    fetch = fetcher or _github_fetch
    repository_id = int(repository["github_repository_id"])
    metadata = fetch(
        f"https://api.github.com/repositories/{repository_id}",
        installation_token,
        "application/vnd.github+json",
        MAX_JSON_BYTES,
        False,
    )
    if not isinstance(metadata, dict) or int(metadata.get("id") or 0) != repository_id:
        raise GitHubWorkspaceError("GitHub returned metadata for an unexpected repository", status_code=502)
    full_name = str(metadata.get("full_name") or "")
    if full_name.lower() != str(repository.get("full_name") or "").lower():
        raise GitHubWorkspaceError("GitHub repository identity changed unexpectedly", status_code=409)
    default_branch = str(metadata.get("default_branch") or "")
    if not default_branch or len(default_branch) > 255:
        raise GitHubWorkspaceError("GitHub returned an invalid default branch", status_code=502)

    commit = fetch(
        _api_url(full_name, f"/commits/{urllib.parse.quote(default_branch)}"),
        installation_token,
        "application/vnd.github+json",
        MAX_JSON_BYTES,
        False,
    )
    languages = fetch(
        _api_url(full_name, "/languages"),
        installation_token,
        "application/vnd.github+json",
        128 * 1024,
        False,
    )
    releases = _optional(
        fetch,
        _api_url(full_name, "/releases?per_page=1"),
        installation_token,
        "application/vnd.github+json",
        256 * 1024,
        False,
    )
    readme = _optional(
        fetch,
        _api_url(full_name, "/readme"),
        installation_token,
        "application/vnd.github.raw+json",
        MAX_README_BYTES,
        True,
    )
    commit_sha = str(commit.get("sha") if isinstance(commit, dict) else "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise GitHubWorkspaceError("GitHub returned an invalid commit SHA", status_code=502)
    tree = fetch(
        _api_url(full_name, f"/git/trees/{commit_sha}?recursive=1"),
        installation_token,
        "application/vnd.github+json",
        MAX_TREE_BYTES,
        False,
    )
    entries = tree.get("tree") if isinstance(tree, dict) else None
    if not isinstance(entries, list):
        raise GitHubWorkspaceError("GitHub returned an unreadable repository tree", status_code=502)
    if tree.get("truncated") or len(entries) > MAX_TREE_ENTRIES:
        raise GitHubWorkspaceError("repository tree exceeds the 10000-entry safety limit", status_code=413)
    paths = [
        str(entry["path"])
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("type") == "blob"
        and isinstance(entry.get("path"), str)
        and len(entry["path"]) <= 500
    ]
    documents = {"README.md": str(readme or "")}
    for selected in SELECTED_DOCUMENT_PATHS:
        if selected not in paths:
            continue
        content = _optional(
            fetch,
            _api_url(full_name, f"/contents/{_content_path(selected)}"),
            installation_token,
            "application/vnd.github.raw+json",
            MAX_DOCUMENT_BYTES,
            True,
        )
        documents[selected] = str(content or "")
    document_terms = {
        path: {
            "proceed": bool(re.search(r"\bPROCEED\b", text)),
            "needsReview": bool(re.search(r"\bNEEDS_REVIEW\b", text)),
            "silence": bool(re.search(r"\bSILENCE\b", text)),
        }
        for path, text in documents.items()
    }
    release = releases[0] if isinstance(releases, list) and releases and isinstance(releases[0], dict) else None
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    commit_record = commit.get("commit") if isinstance(commit, dict) and isinstance(commit.get("commit"), dict) else {}
    committer = commit_record.get("committer") if isinstance(commit_record.get("committer"), dict) else {}
    snapshot = {
        "schema_version": "semeai.repository-evidence.snapshot.v1",
        "source_mode": "LIVE GITHUB SNAPSHOT",
        "captured_at": _captured_at(),
        "repository": full_name,
        "owner": str(owner.get("login") or repository.get("owner") or full_name.split("/", 1)[0]),
        "default_branch": default_branch,
        "commit_sha": commit_sha.lower(),
        "commit_date": str(committer.get("date") or ""),
        "public_metadata": {
            "description": metadata.get("description") if isinstance(metadata.get("description"), str) else None,
            "html_url": str(metadata.get("html_url") or ""),
            "visibility": str(metadata.get("visibility") or ("private" if metadata.get("private") else "public")),
            "fork": bool(metadata.get("fork")),
            "archived": bool(metadata.get("archived")),
            "disabled": bool(metadata.get("disabled")),
            "stars": int(metadata.get("stargazers_count") or 0),
            "forks": int(metadata.get("forks_count") or 0),
            "open_issues": int(metadata.get("open_issues_count") or 0),
            "size_kb": int(metadata.get("size") or 0),
            "created_at": str(metadata.get("created_at") or ""),
            "updated_at": str(metadata.get("updated_at") or ""),
            "pushed_at": str(metadata.get("pushed_at") or ""),
            "license_spdx": (
                str(metadata["license"].get("spdx_id"))
                if isinstance(metadata.get("license"), dict) and metadata["license"].get("spdx_id")
                else None
            ),
            "topics": [str(item) for item in metadata.get("topics", [])[:50]] if isinstance(metadata.get("topics"), list) else [],
            "languages": languages if isinstance(languages, dict) else {},
            "latest_release": (
                {
                    "tag": str(release.get("tag_name") or ""),
                    "published_at": str(release.get("published_at") or ""),
                    "draft": bool(release.get("draft")),
                    "prerelease": bool(release.get("prerelease")),
                }
                if release
                else None
            ),
        },
        "tree": {"entry_count": len(entries), "blob_count": len(paths), "truncated": False},
        "documentation_signals": {
            "selected_paths": [path for path, text in documents.items() if text],
            "documents_with_tristate_terms": [
                path for path, terms in document_terms.items() if all(terms.values())
            ],
        },
    }
    return {"snapshot": snapshot, "paths": paths, "document_terms": document_terms}


def run_canonical_analyzer(
    capture: Mapping[str, Any], *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    values = env or os.environ
    core_path = Path(str(values.get("SEMEAI_BENCHMARK_CORE_PATH") or "").strip()).resolve()
    if not core_path.is_file() or core_path.name != "benchmark.js":
        raise GitHubWorkspaceError("canonical repository benchmark core is not configured", status_code=503)
    source_hash = hashlib.sha256(core_path.read_bytes()).hexdigest()
    expected_hash = str(values.get("SEMEAI_BENCHMARK_CORE_SHA256") or "").strip().lower()
    if expected_hash and not hmac_compare(source_hash, expected_hash):
        raise GitHubWorkspaceError("canonical repository benchmark core hash mismatch", status_code=503)
    node_binary = str(values.get("SEMEAI_NODE_BINARY") or "node").strip()
    node_path = shutil.which(node_binary)
    if not node_path:
        raise GitHubWorkspaceError("Node.js is required for the canonical repository analyzer", status_code=503)
    runner = Path(__file__).with_name("repository_benchmark_runner.js")
    if not runner.is_file():
        raise GitHubWorkspaceError("canonical analyzer runner is unavailable", status_code=503)
    payload = json.dumps(dict(capture), ensure_ascii=False, separators=(",", ":"))
    child_env = {
        key: os.environ[key]
        for key in ("PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP")
        if key in os.environ
    }
    try:
        completed = subprocess.run(
            [node_path, str(runner), str(core_path)],
            input=payload,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=25,
            check=False,
            env=child_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubWorkspaceError("canonical repository analyzer did not complete", status_code=502) from exc
    if completed.returncode != 0 or len(completed.stdout.encode("utf-8")) > 2 * 1024 * 1024:
        raise GitHubWorkspaceError("canonical repository analyzer failed", status_code=502)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubWorkspaceError("canonical repository analyzer returned unreadable output", status_code=502) from exc
    if not isinstance(result, dict):
        raise GitHubWorkspaceError("canonical repository analyzer returned invalid output", status_code=502)
    result["analyzer_source_sha256"] = source_hash
    return result


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(str(left), str(right))


def execute_repository_benchmark(
    auth: Mapping[str, Any],
    repository_id: int,
    *,
    env: Mapping[str, str] | None = None,
    fetcher: GitHubFetcher | None = None,
    installation_requester=None,
) -> dict[str, Any]:
    values = env or os.environ
    repository = get_owned_repository(auth, int(repository_id), env=values)
    token = create_installation_access_token(
        int(repository["installation_id"]), env=values, request_json=installation_requester
    )
    capture = collect_authorized_snapshot(repository, token, fetcher=fetcher)
    result = run_canonical_analyzer(capture, env=values)
    return save_benchmark_run(auth, repository, result, env=values)
