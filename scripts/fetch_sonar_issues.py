#!/usr/bin/env python3
"""Fetch unresolved Sonar issues and emit a source-independent, stable JSON document."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shlex
import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PAGE_SIZE = 500
MAX_ISSUES = 10_000


class FetchError(Exception):
    """A safe-to-display configuration or API error."""


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise FetchError(f"Environment file not found: {path}")
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise FetchError(f"Invalid .env assignment on line {number}")
        try:
            parts = shlex.split(value, comments=True, posix=True)
        except ValueError as error:
            raise FetchError(f"Invalid quoting in .env on line {number}") from error
        if len(parts) > 1:
            raise FetchError(f"Quote values containing whitespace in .env on line {number}")
        values[key] = parts[0] if parts else ""
    return values


def project_key_from_properties(path: Path) -> str:
    if not path.is_file():
        raise FetchError(f"Sonar project configuration not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*sonar\.projectKey\s*=\s*(.*?)\s*$", raw)
        if match and match.group(1) and not match.group(1).startswith("#"):
            return match.group(1)
    raise FetchError(f"sonar.projectKey is missing from {path}")


def request_json(
    base_url: str, token: str, endpoint: str, params: dict, *, timeout: float = 30
) -> dict:
    url = f"{base_url.rstrip('/')}/api/{endpoint}?{urlencode(params)}"
    credential = base64.b64encode(f"{token}:".encode()).decode("ascii")
    request = Request(
        url,
        headers={"Authorization": f"Basic {credential}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise FetchError(
                f"Sonar rejected the configured token or project permissions (HTTP {error.code})"
            ) from None
        raise FetchError(f"Sonar API returned HTTP {error.code}") from None
    except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as error:
        # Network exception messages can contain credentials or server-controlled text.
        raise FetchError(f"Could not read Sonar API response ({type(error).__name__})") from None
    if not isinstance(payload, dict):
        raise FetchError("Sonar API returned an unexpected response")
    return payload


def request_page(
    base_url: str,
    token: str,
    organization: str | None,
    project_key: str,
    page: int,
    branch: str | None = None,
    pull_request: str | None = None,
) -> dict:
    params = {
        "componentKeys": project_key,
        "resolved": "false",
        "ps": str(PAGE_SIZE),
        "p": str(page),
        "s": "CREATION_DATE",
        "asc": "true",
    }
    if organization:
        params["organization"] = organization
    if branch:
        params["branch"] = branch
    if pull_request:
        params["pullRequest"] = pull_request
    payload = request_json(base_url, token, "issues/search", params)
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        raise FetchError("Sonar API returned an unexpected issue response")
    return payload


def normalize_issue(issue: dict, project_key: str, source: str) -> dict:
    if any(
        not isinstance(issue.get(field), str) or not issue[field]
        for field in ("key", "component", "rule")
    ):
        raise FetchError("Sonar API returned missing or invalid issue identifiers")
    component = str(issue.get("component", ""))
    prefix = project_key + ":"
    if component.startswith(prefix):
        component = component[len(prefix) :]
    tags = issue.get("tags") or []
    if not isinstance(tags, list):
        raise FetchError("Sonar API returned invalid issue tags")
    if issue.get("line") is not None and (type(issue["line"]) is not int or issue["line"] < 1):
        raise FetchError("Sonar API returned an invalid issue line")
    return {
        "key": str(issue.get("key", "")),
        "rule": str(issue.get("rule", "")),
        "type": issue.get("type"),
        "severity": issue.get("severity"),
        "status": issue.get("status"),
        "resolution": issue.get("resolution"),
        "path": component,
        "line": issue.get("line"),
        "message": str(issue.get("message", "")),
        "effort": issue.get("effort"),
        "creation_date": issue.get("creationDate"),
        "update_date": issue.get("updateDate"),
        "tags": sorted({str(tag) for tag in tags}),
        "source": source,
    }


def wait_for_analysis(
    root: Path, base_url: str, token: str, project_key: str, timeout: int
) -> None:
    report = root / ".scannerwork/report-task.txt"
    metadata = dict(
        line.split("=", 1)
        for line in report.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    if metadata.get("projectKey") != project_key or not metadata.get("ceTaskId"):
        raise FetchError("Scanner report does not identify a task for the configured project")
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        payload = request_json(
            base_url,
            token,
            "ce/task",
            {"id": metadata["ceTaskId"]},
            timeout=min(30, remaining),
        )
        task = payload.get("task")
        if not isinstance(task, dict):
            raise FetchError("Sonar API returned an invalid background task")
        status = task.get("status")
        if status == "SUCCESS":
            return
        if status not in ("PENDING", "IN_PROGRESS"):
            raise FetchError("Sonar analysis failed, was canceled, or returned an unknown status")
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise FetchError("Timed out waiting for Sonar analysis")


def fetch(args: argparse.Namespace) -> dict | None:
    root = args.root.resolve()
    env_path = args.env_file if args.env_file.is_absolute() else root / args.env_file
    env = read_env(env_path)
    project_key = project_key_from_properties(root / "sonar-project.properties")

    if args.source == "cloud":
        token = env.get("SONAR_CLOUD_TOKEN", "").strip()
        organization = env.get("SONAR_ORGANIZATION", "").strip()
        base_url = "https://sonarcloud.io"
        if not token:
            raise FetchError("SONAR_CLOUD_TOKEN is required in .env for SonarCloud")
        if not organization:
            raise FetchError("SONAR_ORGANIZATION is required in .env for SonarCloud")
    else:
        token = env.get("SONAR_TOKEN", "").strip()
        if not token:
            raise FetchError("SONAR_TOKEN is required in .env for local SonarQube")
        port = env.get("SONAR_PORT", "9000").strip() or "9000"
        if not re.fullmatch(r"[0-9]+", port) or not 1 <= int(port) <= 65535:
            raise FetchError("SONAR_PORT in .env must be a valid TCP port")
        base_url = f"http://127.0.0.1:{port}"
        organization = None

    if args.wait_for_analysis or args.wait_only:
        wait_for_analysis(root, base_url, token, project_key, args.analysis_timeout)
    if args.wait_only:
        return None

    all_issues: dict[str, dict] = {}
    page = 1
    expected_total: int | None = None
    while True:
        payload = request_page(
            base_url, token, organization, project_key, page, args.branch, args.pull_request
        )
        paging = payload.get("paging")
        if not isinstance(paging, dict):
            raise FetchError("Sonar API returned missing or invalid paging metadata")
        total = paging.get("total")
        if type(total) is not int or total < 0:
            raise FetchError("Sonar API returned an invalid issue count")
        if paging.get("pageIndex") != page or paging.get("pageSize") != PAGE_SIZE:
            raise FetchError("Sonar API returned unexpected pagination")
        if "total" in payload and payload["total"] != total:
            raise FetchError("Sonar API returned inconsistent issue counts")
        if expected_total is None:
            expected_total = total
            if expected_total > MAX_ISSUES:
                raise FetchError(
                    f"The API reports {expected_total} issues; refusing to truncate at {MAX_ISSUES}"
                )
        elif total != expected_total:
            raise FetchError(
                "Issue count changed during pagination; retry after analysis completes"
            )
        expected_size = min(PAGE_SIZE, expected_total - (page - 1) * PAGE_SIZE)
        if len(payload["issues"]) != expected_size:
            raise FetchError("Sonar API returned an incomplete issue page; retry the extraction")
        for raw_issue in payload["issues"]:
            if not isinstance(raw_issue, dict) or not isinstance(raw_issue.get("key"), str):
                raise FetchError("Sonar API returned an invalid issue")
            normalized = normalize_issue(raw_issue, project_key, args.source)
            if not normalized["key"] or normalized["key"] in all_issues:
                raise FetchError(
                    "Sonar API returned missing or duplicate issue keys; retry extraction"
                )
            all_issues[normalized["key"]] = normalized
        if page * PAGE_SIZE >= expected_total:
            break
        page += 1

    issues = sorted(
        all_issues.values(),
        key=lambda item: (
            item["path"].casefold(),
            item["path"],
            item["line"] if isinstance(item["line"], int) else 0,
            item["rule"],
            item["key"],
        ),
    )
    document = {
        "schema_version": 1,
        "source": args.source,
        "server_url": base_url,
        "organization": organization,
        "project_key": project_key,
        "total": len(issues),
        "issues": issues,
    }
    if args.branch:
        document["branch"] = args.branch
    if args.pull_request:
        document["pull_request"] = args.pull_request
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("cloud", "local"), required=True)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Credentials file (default: .env under --root)",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    context = parser.add_mutually_exclusive_group()
    context.add_argument("--branch", help="Analyze this branch (default: server's main branch)")
    context.add_argument("--pull-request", help="Analyze this pull request")
    parser.add_argument(
        "--wait-for-analysis",
        action="store_true",
        help="Wait for the task in .scannerwork/report-task.txt before fetching",
    )
    parser.add_argument(
        "--wait-only", action="store_true", help="Wait for analysis without fetching"
    )
    parser.add_argument(
        "--analysis-timeout", type=int, default=300, help="Analysis wait limit in seconds"
    )
    args = parser.parse_args()
    if args.analysis_timeout < 1:
        parser.error("--analysis-timeout must be positive")
    try:
        document = fetch(args)
        if document is None:
            return 0
        serialized = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            write_output(args.output, serialized)
        else:
            sys.stdout.write(serialized)
    except (FetchError, OSError, UnicodeError) as error:
        print(f"sonarqube-issues: {error}", file=sys.stderr)
        return 2
    return 0


def write_output(path: Path, serialized: str) -> None:
    """Replace output only after a complete, successful extraction and write."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(serialized)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
