"""e2e 실행 기록의 요약 표 (#2823)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "render_e2e_records.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_e2e_records", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render_mod = _load()


def _cli(args: list[str], **kw: Any) -> dict[str, Any]:
    step = {
        "kind": "cli",
        "args": args,
        "returncode": 0,
        "status": "ok",
        "code": None,
        "expect_failure": False,
        "failed": False,
        "count": 1,
        "seconds": 0.5,
    }
    step.update(kw)
    return step


def _record(nodeid: str, outcome: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 1,
        "nodeid": nodeid,
        "outcome": outcome,
        "seconds": 12.5,
        "net_attempts": 1,
        "steps": steps,
    }


def _write(directory: Path, name: str, record: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(record), encoding="utf-8")


def _run(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(directory)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_summary_and_details(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "b.json",
        _record(
            "tests/e2e/test_b.py::test_fails",
            "failed",
            [
                {"kind": "start", "ok": True, "ready_seconds": 1.25},
                _cli(["bot", "list"], count=4, seconds=2.0),
                _cli(
                    ["bot", "start", "x"],
                    returncode=1,
                    status="error",
                    code="BOT_NOT_FOUND",
                    failed=True,
                ),
                _cli(
                    ["bot", "start", "y"],
                    returncode=1,
                    status="error",
                    code="BOT_NOT_FOUND",
                    failed=True,
                    expect_failure=True,
                ),
            ],
        ),
    )
    _write(tmp_path, "a.json", _record("tests/e2e/test_a.py::test_ok", "passed", []))
    out = render_mod.render(tmp_path)
    lines = out.splitlines()
    header = lines.index(
        "| 시나리오 | 결과 | 시간(초) | CLI 호출 | 실패한 호출 | 외부 접속 시도 |"
    )
    assert lines[header + 2] == (
        "| <code>tests/e2e/test_a.py::test_ok</code> | 통과 | 12.50 | 0 | 0 | 1 |"
    )
    assert lines[header + 3] == (
        "| <code>tests/e2e/test_b.py::test_fails</code> | 실패 | 12.50 | 6 | 1 | 1 |"
    )
    assert "| 1 | 데몬 시작 | - | - | - | 준비 1.25초 |" in lines
    assert "| 2 | <code>bot list</code> ×4 | 0 | ok | - | 2.00 |" in lines
    tail = " | 1 | error | BOT_NOT_FOUND | 0.50 |"
    assert "| 3 | <code>bot start x</code> (기대와 다름)" + tail in lines
    assert "| 4 | <code>bot start y</code> (실패 기대)" + tail in lines
    assert out.count("<details>") == 2


def test_table_cells_are_escaped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.json",
        _record("tests/e2e/t.py::t", "passed", [_cli(["--name", "a|b <i>"])]),
    )
    out = render_mod.render(tmp_path)
    assert "<code>--name 'a&#124;b &lt;i&gt;'</code>" in out
    assert "<i>" not in out


def test_missing_directory_exits_zero(tmp_path: Path) -> None:
    proc = _run(tmp_path / "absent")
    assert proc.returncode == 0
    assert "기록이 없다" in proc.stdout


def test_empty_directory_exits_zero(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert "기록 디렉터리가 비어 있다" in proc.stdout


def test_broken_records_are_named_and_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    _write(tmp_path, "old.json", {"version": 0, "nodeid": "x", "steps": []})
    _write(tmp_path, "list.json", [1, 2])
    _write(tmp_path, "ok.json", _record("tests/e2e/t.py::t", "passed", []))
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert "<code>tests/e2e/t.py::t</code>" in proc.stdout
    assert (
        "읽지 못한 기록 3개: <code>bad.json</code>, <code>list.json</code>,"
        " <code>old.json</code>" in proc.stdout
    )


def test_render_error_still_exits_zero(tmp_path: Path, monkeypatch: Any) -> None:
    def _boom(path: Path) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(render_mod, "render", _boom)
    assert render_mod.main([str(tmp_path)]) == 0
