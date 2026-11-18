"""Autopilot queue collection script tests (#2538)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO = "example/repo"

FAKE_GH = """#!{python}
import json
import sys
from pathlib import Path

state_dir = Path({state_dir!r})
with (state_dir / "calls.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
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


def _page(
    items: list[Any], *, total_count: int = 0, incomplete: bool = False
) -> dict[str, Any]:
    return {
        "stdout": json.dumps(
            {
                "total_count": total_count,
                "incomplete_results": incomplete,
                "items": items,
            }
        ),
        "exit": 0,
    }


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        FAKE_GH.format(python=sys.executable, state_dir=str(tmp_path)), encoding="utf-8"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

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


def _run(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    script = _load_script()
    code = script.main(["--repo", REPO])
    return code, capsys.readouterr().out


def test_uses_get_method(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    log = fake_gh([_page([{"number": 1}], total_count=1), _page([])])

    code, _ = _run(capsys)

    assert code == 0
    search_calls = [c for c in _calls(log) if "search/issues" in c]
    assert search_calls
    for call in search_calls:
        index = call.index("--method")
        assert call[index + 1] == "GET"


def test_stops_on_empty_page(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    log = fake_gh(
        [
            _page([{"number": 1}], total_count=2),
            _page([{"number": 2}], total_count=2),
            _page([], total_count=2),
            _page([{"number": 99}], total_count=2),
        ]
    )

    code, _ = _run(capsys)

    assert code == 0
    calls = _calls(log)
    assert len(calls) == 3
    pages = [next(a for a in c if a.startswith("page=")) for c in calls]
    assert pages == ["page=1", "page=2", "page=3"]


def test_merges_pages_into_one_array(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(
        [
            _page([{"number": 1}, {"number": 2}], total_count=3),
            _page([{"number": 3}], total_count=3),
            _page([], total_count=3),
        ]
    )

    code, out = _run(capsys)

    assert code == 0
    assert json.loads(out) == [{"number": 1}, {"number": 2}, {"number": 3}]


def test_stops_at_page_cap(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    script = _load_script()
    log = fake_gh([_page([{"number": 1}], total_count=1000)])

    code, out = _run(capsys)

    assert code == 0
    assert len(_calls(log)) == script.MAX_PAGES
    assert len(json.loads(out)) == script.MAX_PAGES


def test_fails_on_gh_error(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_gh([{"stdout": json.dumps({"message": "Not Found"}), "exit": 1}])

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_fails_on_gh_error_after_first_page(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(
        [
            _page([{"number": 1}], total_count=2),
            {"stdout": json.dumps({"message": "Not Found"}), "exit": 1},
        ]
    )

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_fails_on_non_json(fake_gh, capsys: pytest.CaptureFixture[str]) -> None:
    fake_gh([{"stdout": "<html>oops</html>", "exit": 0}])

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_fails_on_missing_items_key(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([{"stdout": json.dumps({"message": "Not Found"}), "exit": 0}])

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_fails_on_incomplete_results(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_page([{"number": 1}], total_count=1, incomplete=True), _page([])])

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_fails_when_total_count_exceeds_cap(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh([_page([{"number": 1}], total_count=1001), _page([])])

    code, out = _run(capsys)

    assert code == 1
    assert out == ""


def test_query_excludes_default_labels(
    fake_gh, capsys: pytest.CaptureFixture[str]
) -> None:
    log = fake_gh([_page([])])

    code, _ = _run(capsys)

    assert code == 0
    (call,) = _calls(log)
    query = next(a for a in call if a.startswith("q="))[len("q=") :]
    tokens = query.split()
    assert f"repo:{REPO}" in tokens
    assert {"is:issue", "is:open", "sort:created-asc"} <= set(tokens)
    for label in (
        "needs-triage",
        "question",
        "blocked",
        "blocked:review-loop",
        "blocked:pr-review-loop",
        "process",
        "epic",
    ):
        assert f"-label:{label}" in tokens
