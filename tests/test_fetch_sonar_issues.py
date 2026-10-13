"""Extraction must be complete, stable and fail without replacing previous results."""

import argparse
import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/fetch_sonar_issues.py"
spec = importlib.util.spec_from_file_location("fetch_sonar_issues", SCRIPT)
assert spec is not None and spec.loader is not None
sonar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sonar)


@pytest.fixture
def args(tmp_path):
    (tmp_path / ".env").write_text(
        'SONAR_TOKEN="local-secret"\nSONAR_CLOUD_TOKEN=cloud-secret\nSONAR_ORGANIZATION=org\n',
        encoding="utf-8",
    )
    (tmp_path / "sonar-project.properties").write_text("sonar.projectKey=project\n")
    return argparse.Namespace(
        root=tmp_path,
        env_file=Path(".env"),
        source="local",
        branch=None,
        pull_request=None,
        wait_for_analysis=False,
        wait_only=False,
        analysis_timeout=5,
    )


def issue(key, path="app/a.py", **fields):
    return {"key": key, "component": f"project:{path}", "rule": "python:S1", **fields}


def page(issues, total=None, index=1):
    return {
        "issues": issues,
        "paging": {
            "total": len(issues) if total is None else total,
            "pageIndex": index,
            "pageSize": sonar.PAGE_SIZE,
        },
    }


def test_complete_pagination_and_stable_serialization(args, monkeypatch):
    monkeypatch.setattr(sonar, "PAGE_SIZE", 2)
    items = [issue("b", line=2), issue("a", line=1, tags=["z", "a", "z"])]
    calls = []

    def request(*parameters):
        calls.append(parameters[4])
        return page(items, total=3) if parameters[4] == 1 else page([issue("c")], 3, 2)

    monkeypatch.setattr(sonar, "request_page", request)
    first = sonar.fetch(args)
    items.reverse()
    second = sonar.fetch(args)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert calls == [1, 2, 1, 2]
    assert first["total"] == 3
    assert [item["key"] for item in first["issues"]] == ["c", "a", "b"]
    assert first["issues"][1]["tags"] == ["a", "z"]


@pytest.mark.parametrize(
    "payload",
    [
        {"issues": []},
        page([], total=-1),
        page([], total="0"),
        page([], total=True),
        page([], total=10_001),
        page([], total=1),
        page([issue("a")], total=0),
        page([issue("a")], index=2),
        page([issue("a"), issue("a")]),
        page([issue("")]),
        page([{"key": 1}]),
        page([None]),
        page([issue("a", tags="bad")]),
        page([issue("a", line="12")]),
        {**page([]), "total": 1},
    ],
)
def test_invalid_or_partial_responses_fail(args, monkeypatch, payload):
    monkeypatch.setattr(sonar, "request_page", lambda *parameters: payload)
    with pytest.raises(sonar.FetchError):
        sonar.fetch(args)


@pytest.mark.parametrize("second", [page([], 0, 2), page([issue("a")], 2, 2)])
def test_changing_counts_and_repeated_pages_are_bounded(args, monkeypatch, second):
    monkeypatch.setattr(sonar, "PAGE_SIZE", 1)
    calls = []

    def request(*parameters):
        calls.append(parameters[4])
        return page([issue("a")], 2) if parameters[4] == 1 else second

    monkeypatch.setattr(sonar, "request_page", request)
    with pytest.raises(sonar.FetchError):
        sonar.fetch(args)
    assert calls == [1, 2]


def test_empty_project(args, monkeypatch):
    monkeypatch.setattr(sonar, "request_page", lambda *parameters: page([]))
    assert sonar.fetch(args)["issues"] == []


@pytest.mark.parametrize("context,value", [("branch", "feature/a"), ("pull_request", "42")])
def test_cloud_context_is_explicit(args, monkeypatch, context, value):
    args.source = "cloud"
    setattr(args, context, value)
    captured = []
    monkeypatch.setattr(
        sonar, "request_page", lambda *parameters: captured.append(parameters) or page([])
    )
    document = sonar.fetch(args)
    assert captured[0] == (
        "https://sonarcloud.io",
        "cloud-secret",
        "org",
        "project",
        1,
        args.branch,
        args.pull_request,
    )
    assert document[context] == value


def test_request_encodes_context_and_uses_authentication(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(page([])).encode()

    captured = []
    monkeypatch.setattr(
        sonar, "urlopen", lambda request, timeout: captured.append(request) or Response()
    )
    sonar.request_page("https://sonarcloud.io", "secret", "org", "project", 1, "feature/a & b")
    request = captured[0]
    assert "branch=feature%2Fa+%26+b" in request.full_url
    assert "s=CREATION_DATE&asc=true" in request.full_url
    assert "secret" not in request.full_url
    assert request.get_header("Authorization").startswith("Basic ")


@pytest.mark.parametrize(
    "error", [HTTPError("https://server", 401, "secret", {}, None), URLError("secret")]
)
def test_network_failures_do_not_expose_credentials(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(sonar, "urlopen", fail)
    with pytest.raises(sonar.FetchError) as failure:
        sonar.request_page("https://server", "secret", None, "project", 1)
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize("status", ["FAILED", "CANCELED", "UNKNOWN"])
def test_analysis_failure(args, monkeypatch, status):
    write_report(args.root)
    args.wait_only = True
    monkeypatch.setattr(
        sonar, "request_json", lambda *parameters, **kwargs: {"task": {"status": status}}
    )
    with pytest.raises(sonar.FetchError):
        sonar.fetch(args)


def write_report(root):
    (root / ".scannerwork").mkdir()
    (root / ".scannerwork/report-task.txt").write_text("projectKey=project\nceTaskId=task\n")


def test_analysis_waits_for_success(args, monkeypatch):
    write_report(args.root)
    args.wait_only = True
    statuses = iter(["PENDING", "IN_PROGRESS", "SUCCESS"])
    monkeypatch.setattr(sonar.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sonar, "request_json", lambda *parameters, **kwargs: {"task": {"status": next(statuses)}}
    )
    assert sonar.fetch(args) is None


def test_analysis_wait_is_bounded(args, monkeypatch):
    write_report(args.root)
    ticks = iter([0, 6])
    monkeypatch.setattr(sonar.time, "monotonic", lambda: next(ticks))
    with pytest.raises(sonar.FetchError, match="Timed out"):
        sonar.wait_for_analysis(args.root, "http://server", "token", "project", 5)


def test_env_parsing_does_not_execute_shell(tmp_path):
    env = tmp_path / ".env"
    env.write_text('export TOKEN="$(touch sentinel)" # comment\nEMPTY=\n')
    assert sonar.read_env(env) == {"TOKEN": "$(touch sentinel)", "EMPTY": ""}
    env.write_text("TOKEN=unexpected whitespace\n")
    with pytest.raises(sonar.FetchError, match="Quote values"):
        sonar.read_env(env)


def test_cli_failure_preserves_output(args, monkeypatch, capsys):
    output = args.root / "issues.json"
    output.write_text("previous result")
    monkeypatch.setattr(sonar, "request_page", lambda *parameters: page([], total=1))
    monkeypatch.setattr(
        sonar.sys,
        "argv",
        [str(SCRIPT), "--source", "local", "--root", str(args.root), "--output", str(output)],
    )
    assert sonar.main() == 2
    assert output.read_text() == "previous result"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "secret" not in captured.err


def test_output_is_replaced_after_success(tmp_path):
    output = tmp_path / "issues.json"
    output.write_text("previous")
    sonar.write_output(output, '{"issues": []}\n')
    assert output.read_text() == '{"issues": []}\n'
    assert list(tmp_path.iterdir()) == [output]
