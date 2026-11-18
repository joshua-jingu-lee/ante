"""Autopilot queue collection script tests (#2538)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPILOT_DOC = REPO_ROOT / ".agent" / "commands" / "autopilot.md"
REPO = "example/repo"
PER_PAGE = 100

FAKE_GH_IMPL = """import json
import sys
from pathlib import Path

state_dir = Path({state_dir!r})
args = sys.argv[1:]
with (state_dir / "calls.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
if args[:2] == ["repo", "view"]:
    sys.stdout.write(json.dumps({{"nameWithOwner": "owner/from-gh"}}))
    sys.exit(0)
counter = state_dir / "counter"
index = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(index + 1))
responses = json.loads((state_dir / "responses.json").read_text())
response = responses[min(index, len(responses) - 1)]
sys.stdout.write(response["stdout"])
sys.exit(response["exit"])
"""


def _load_script() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "collect_autopilot_queue.py"
    spec = importlib.util.spec_from_file_location(
        "collect_autopilot_queue", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load queue script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue(number: int, *, body: str | None = "long body") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"이슈 {number}",
        "labels": [{"name": "bug", "color": "d73a4a"}],
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "body": body,
        "user": {"login": "someone"},
    }


def _slim(number: int, *, body: str = "long body") -> dict[str, Any]:
    return {
        "number": number,
        "title": f"이슈 {number}",
        "labels": ["bug"],
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "body": body,
    }


def _issues(start: int, count: int) -> list[dict[str, Any]]:
    return [_issue(n) for n in range(start, start + count)]


def _page(
    items: list[Any],
    *,
    total_count: Any,
    incomplete: bool = False,
    omit_total: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"incomplete_results": incomplete, "items": items}
    if not omit_total:
        payload["total_count"] = total_count
    return {"stdout": json.dumps(payload), "exit": 0}


def _raw(stdout: str, exit_code: int = 0) -> dict[str, Any]:
    return {"stdout": stdout, "exit": exit_code}


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    impl = tmp_path / "fake_gh.py"
    impl.write_text(FAKE_GH_IMPL.format(state_dir=str(tmp_path)), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    def configure(responses: list[dict[str, Any]]) -> Path:
        (tmp_path / "responses.json").write_text(
            json.dumps(responses), encoding="utf-8"
        )
        return tmp_path / "calls.jsonl"

    return configure


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _search_calls(log: Path) -> list[list[str]]:
    return [c for c in _calls(log) if "search/issues" in c]


def _run(
    capsys: pytest.CaptureFixture[str], argv: list[str] | None = None
) -> tuple[int, str, str]:
    script = _load_script()
    code = script.main(["--repo", REPO] if argv is None else argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _assert_failed(capsys: pytest.CaptureFixture[str], expected_err: str) -> None:
    code, out, err = _run(capsys)
    assert code == 1
    assert out == ""
    assert expected_err in err


def _documented_excluded_labels() -> set[str]:
    lines = AUTOPILOT_DOC.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("### 기본 제외 대상")
    except ValueError:
        pytest.fail("autopilot.md has no '### 기본 제외 대상' section")
    labels: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("###"):
            break
        match = re.match(r"^- `([^`]+)`$", line)
        if match:
            labels.add(match.group(1))
    if not labels:
        pytest.fail("no label lines read from '### 기본 제외 대상'")
    return labels


def test_uses_get_method(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    log = fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=101),
            _page(_issues(101, 1), total_count=101),
        ]
    )

    code, _, _ = _run(capsys)

    assert code == 0
    search_calls = _search_calls(log)
    assert len(search_calls) == 2
    for call in search_calls:
        index = call.index("--method")
        assert call[index + 1] == "GET"


def test_stops_on_empty_page(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    log = fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=200),
            _page(_issues(101, PER_PAGE), total_count=200),
            _page([], total_count=200),
            _page(_issues(900, 1), total_count=200),
        ]
    )

    code, out, _ = _run(capsys)

    assert code == 0
    calls = _search_calls(log)
    assert len(calls) == 3
    pages = [next(a for a in c if a.startswith("page=")) for c in calls]
    assert pages == ["page=1", "page=2", "page=3"]
    assert len(json.loads(out)) == 2 * PER_PAGE


def test_stops_on_short_page(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    log = fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=103),
            _page(_issues(101, 3), total_count=103),
            _page(_issues(900, 1), total_count=103),
        ]
    )

    code, out, _ = _run(capsys)

    assert code == 0
    assert len(_search_calls(log)) == 2
    assert len(json.loads(out)) == PER_PAGE + 3


def test_merges_pages_into_one_slim_array(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=102),
            _page([_issue(101), _issue(102, body=None)], total_count=102),
        ]
    )

    code, out, _ = _run(capsys)

    assert code == 0
    expected = [_slim(n) for n in range(1, 102)] + [_slim(102, body="")]
    assert json.loads(out) == expected
    assert out.isascii()


def test_stops_at_page_cap(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    script = _load_script()
    total = script.MAX_PAGES * PER_PAGE
    log = fake_gh(
        [
            _page(_issues(page * PER_PAGE + 1, PER_PAGE), total_count=total)
            for page in range(script.MAX_PAGES + 1)
        ]
    )

    code, out, _ = _run(capsys)

    assert code == 0
    assert len(_search_calls(log)) == script.MAX_PAGES
    assert len(json.loads(out)) == total


def test_resolves_repo_without_flag(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    log = fake_gh([_page([], total_count=0)])

    code, out, _ = _run(capsys, [])

    assert code == 0
    assert json.loads(out) == []
    calls = _calls(log)
    assert calls[0] == ["repo", "view", "--json", "nameWithOwner"]
    (search,) = _search_calls(log)
    query = next(a for a in search if a.startswith("q="))[len("q=") :]
    assert "repo:owner/from-gh" in query.split()


def test_fails_on_gh_error(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_gh([_raw(json.dumps({"message": "Not Found"}), 1)])

    _assert_failed(capsys, "gh api search/issues page 1: gh exited 1")


def test_fails_on_gh_error_after_first_page(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=150),
            _raw(json.dumps({"message": "Not Found"}), 1),
        ]
    )

    _assert_failed(capsys, "gh api search/issues page 2: gh exited 1")


def test_fails_when_gh_not_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    _assert_failed(capsys, "cannot run gh")


def test_fails_on_non_json(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_gh([_raw("<html>oops</html>")])

    _assert_failed(capsys, "response is not JSON")


def test_fails_on_non_object_response(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_raw(json.dumps([1, 2, 3]))])

    _assert_failed(capsys, "response is not a JSON object")


def test_fails_on_missing_items_key(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_raw(json.dumps({"message": "Not Found"}))])

    _assert_failed(capsys, "response has no 'items' array")


def test_fails_on_item_missing_field(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    item = _issue(1)
    del item["html_url"]
    fake_gh([_page([item], total_count=1)])

    _assert_failed(capsys, "is missing field")


def test_fails_on_incomplete_results(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_page(_issues(1, 1), total_count=1, incomplete=True)])

    _assert_failed(capsys, "incomplete_results is true")


def test_fails_when_total_count_exceeds_cap(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_page(_issues(1, 1), total_count=1001)])

    _assert_failed(capsys, "exceeds the search API cap")


@pytest.mark.parametrize(
    "page",
    [
        _page(_issues(1, 1), total_count=None, omit_total=True),
        _page(_issues(1, 1), total_count="1"),
        _page(_issues(1, 1), total_count=None),
    ],
    ids=["missing", "string", "null"],
)
def test_fails_when_total_count_invalid(
    fake_gh, capsys: pytest.CaptureFixture[str], page: dict[str, Any]
) -> None:
    fake_gh([page])

    _assert_failed(capsys, "total_count missing or not an integer")


def test_fails_when_count_differs_from_total(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    # An issue closed between pages: page 2 shrinks and total_count drops.
    fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=103),
            _page(_issues(102, 2), total_count=101),
        ]
    )

    _assert_failed(capsys, "queue changed during collection")


def test_fails_on_duplicate_numbers(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    # An issue opened before page 1 shifts #100 onto page 2 as well.
    fake_gh(
        [
            _page(_issues(1, PER_PAGE), total_count=102),
            _page(_issues(100, 2), total_count=102),
        ]
    )

    _assert_failed(capsys, "queue changed during collection")


def test_query_excludes_default_labels(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    documented = _documented_excluded_labels()
    assert set(script.EXCLUDED_LABELS) == documented

    log = fake_gh([_page([], total_count=0)])

    code, _, _ = _run(capsys)

    assert code == 0
    (call,) = _search_calls(log)
    query = next(a for a in call if a.startswith("q="))[len("q=") :]
    tokens = query.split()
    assert f"repo:{REPO}" in tokens
    assert {"is:issue", "is:open", "sort:created-asc"} <= set(tokens)
    for label in documented:
        assert f"-label:{label}" in tokens
