"""``scripts/compare_error_exit_records.py``의 분류와 종료 코드 (#2664).

스크립트는 하위 프로세스로 돌린다. 기록은 기록기와 같은 모양의 JSON Lines다.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import coverage
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compare_error_exit_records.py"

NODE = "tests/unit/x.py::test_x"
JSON_ARGS = ["--format", "json", "report", "view", "r-1"]
TEXT_ARGS = ["--format", "text", "report", "view", "r-1"]
CODE = "BOT_NOT_FOUND"
ALLOWED = "tests/unit/cli/test_single_error_exit.py::test_registry_entries_text_mode"


def _b64(text: str | None) -> str | None:
    return None if text is None else base64.b64encode(text.encode()).decode()


def _row(
    args: list[str],
    *,
    stdout: str = "",
    stderr: str | None = "",
    exit_code: int = 1,
    n: int = 0,
    nodeid: str = NODE,
) -> dict[str, object]:
    return {
        "nodeid": nodeid,
        "n": n,
        "args": args,
        "exit": exit_code,
        "stdout": _b64(stdout),
        "stderr": _b64(stderr),
        "raised": None,
    }


def _write(path: Path, rows: list[dict[str, object]]) -> str:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return str(path)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT / "src"), env.get("PYTHONPATH")) if p
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _compare(
    tmp_path: Path,
    before: list[dict[str, object]],
    after: list[dict[str, object]],
    *extra: str,
    before_again: list[dict[str, object]] | None = None,
    covered: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    covered_path = tmp_path / "covered.json"
    covered_path.write_text(json.dumps(list(covered)), encoding="utf-8")
    return _run(
        "compare",
        _write(tmp_path / "b1.jsonl", before),
        _write(tmp_path / "b2.jsonl", before if before_again is None else before_again),
        _write(tmp_path / "a.jsonl", after),
        "--covered",
        str(covered_path),
        *extra,
    )


def _counts(out: str) -> dict[str, int]:
    head = out.split("\n\n", 1)[0].splitlines()[1:]
    return {k: int(v) for k, v in (line.rsplit(": ", 1) for line in head)}


def _expected_counts(**nonzero: int) -> dict[str, int]:
    counts = {
        "같음": 0,
        "text 형식": 0,
        "의도한 동작 변경": 0,
        "다름": 0,
        "비결정": 0,
        "비결정 실패 행": 0,
        "비결정 실패 행(옮기는 줄을 지남)": 0,
        "후에만 있음": 0,
        "후에만 있음(허용 밖)": 0,
    }
    counts.update(nonzero)
    return counts


def _envelope(code: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": "없음"}) + "\n"


def test_identical_rows_are_same(tmp_path: Path) -> None:
    rows = [_row(JSON_ARGS, stdout='{"status": "error"}\n')]
    result = _compare(tmp_path, rows, rows)
    assert result.returncode == 0, result.stderr
    assert _counts(result.stdout) == _expected_counts(같음=1)


def test_full_output_for_one_text_format_row(tmp_path: Path) -> None:
    before = [_row(TEXT_ARGS, stderr="Error: 없음\n")]
    after = [_row(TEXT_ARGS, stderr=f"Error: {CODE}: 없음\n")]
    result = _compare(tmp_path, before, after)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "# 분류별 행 수\n"
        "같음: 0\n"
        "text 형식: 1\n"
        "의도한 동작 변경: 0\n"
        "다름: 0\n"
        "비결정: 0\n"
        "비결정 실패 행: 0\n"
        "비결정 실패 행(옮기는 줄을 지남): 0\n"
        "후에만 있음: 0\n"
        "후에만 있음(허용 밖): 0\n"
        "\n"
        "# 다름 행 (0)\n"
        "\n"
        "# text 형식 행 (1)\n"
        f"- {NODE}#0 args={TEXT_ARGS}\n"
        "\n"
        "# 비결정 행 (0)\n"
        "\n"
        "# 후에만 있음 행 (0)\n"
    )
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("args", "expected", "exit_code"),
    [
        pytest.param(TEXT_ARGS, "text 형식", 0, id="text-mode"),
        pytest.param(JSON_ARGS, "다름", 1, id="json-mode"),
    ],
)
def test_code_prefix_counts_only_in_text_mode(
    tmp_path: Path, args: list[str], expected: str, exit_code: int
) -> None:
    before = [_row(args, stderr="Error: 없음\n")]
    after = [_row(args, stderr=f"Error: {CODE}: 없음\n")]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


@pytest.mark.parametrize(
    ("code", "expected", "exit_code"),
    [
        pytest.param(CODE, "text 형식", 0, id="registry-code"),
        pytest.param("NOT_A_REGISTRY_CODE", "다름", 1, id="unknown-code"),
        pytest.param("EXECUTION_ERROR", "다름", 1, id="fallback-code"),
    ],
)
def test_prefix_code_must_be_a_registry_code_other_than_the_fallback(
    tmp_path: Path, code: str, expected: str, exit_code: int
) -> None:
    before = [_row(TEXT_ARGS, stderr="Error: 없음\n")]
    after = [_row(TEXT_ARGS, stderr=f"Error: {code}: 없음\n")]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


@pytest.mark.parametrize(
    ("json_code", "expected", "exit_code"),
    [
        pytest.param(CODE, "text 형식", 0, id="same-code"),
        pytest.param("MEMBER_NOT_FOUND", "다름", 1, id="other-code"),
    ],
)
def test_prefix_code_must_match_the_json_row_for_the_same_arguments(
    tmp_path: Path, json_code: str, expected: str, exit_code: int
) -> None:
    json_row = _row(JSON_ARGS, stdout=_envelope(json_code), n=1)
    before = [_row(TEXT_ARGS, stderr="Error: 없음\n"), json_row]
    after = [_row(TEXT_ARGS, stderr=f"Error: {CODE}: 없음\n"), json_row]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(같음=1, **{expected: 1})


@pytest.mark.parametrize(
    ("after_stderr", "expected", "exit_code"),
    [
        pytest.param(f"앞줄\nError: {CODE}: 없음\n", "text 형식", 0, id="one"),
        pytest.param(f"앞줄!\nError: {CODE}: 없음\n", "다름", 1, id="two"),
        pytest.param(f"앞줄\nError: {CODE}: 없다\n", "다름", 1, id="message"),
    ],
)
def test_only_one_line_may_change(
    tmp_path: Path, after_stderr: str, expected: str, exit_code: int
) -> None:
    before = [_row(TEXT_ARGS, stderr="앞줄\nError: 없음\n")]
    after = [_row(TEXT_ARGS, stderr=after_stderr)]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


@pytest.mark.parametrize(
    ("after_exit", "expected", "exit_code"),
    [
        pytest.param(1, "text 형식", 0, id="same-exit"),
        pytest.param(2, "다름", 1, id="other-exit"),
    ],
)
def test_exit_code_must_match(
    tmp_path: Path, after_exit: int, expected: str, exit_code: int
) -> None:
    before = [_row(TEXT_ARGS, stderr="Error: 없음\n")]
    after = [_row(TEXT_ARGS, stderr=f"Error: {CODE}: 없음\n", exit_code=after_exit)]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


@pytest.mark.parametrize(
    ("after_stdout", "expected", "exit_code"),
    [
        pytest.param(f"Error: {CODE}: 없음\n", "text 형식", 0, id="prefixed"),
        pytest.param("Error: 없다\n", "다름", 1, id="other"),
    ],
)
def test_mixed_stderr_applies_to_stdout(
    tmp_path: Path, after_stdout: str, expected: str, exit_code: int
) -> None:
    before = [_row(TEXT_ARGS, stdout="Error: 없음\n", stderr=None)]
    after = [_row(TEXT_ARGS, stdout=after_stdout, stderr=None)]
    result = _compare(tmp_path, before, after)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


def test_row_missing_after_is_different(tmp_path: Path) -> None:
    rows = [_row(JSON_ARGS), _row(JSON_ARGS, n=1)]
    result = _compare(tmp_path, rows, rows[:1])
    assert result.returncode == 1
    assert _counts(result.stdout) == _expected_counts(같음=1, 다름=1)
    assert "  후: 없음\n" in result.stdout


@pytest.mark.parametrize(
    ("nodeid", "extra", "outside", "exit_code"),
    [
        pytest.param(ALLOWED, (), 0, 0, id="constant"),
        pytest.param(NODE, ("--allow-after-only", NODE), 0, 0, id="argument"),
        pytest.param(NODE, (), 1, 1, id="outside"),
    ],
)
def test_rows_only_after_must_belong_to_an_allowed_nodeid(
    tmp_path: Path, nodeid: str, extra: tuple[str, ...], outside: int, exit_code: int
) -> None:
    rows = [_row(JSON_ARGS)]
    after = [*rows, _row(JSON_ARGS, n=1, nodeid=nodeid)]
    result = _compare(tmp_path, rows, after, *extra)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(
        같음=1, **{"후에만 있음": 1, "후에만 있음(허용 밖)": outside}
    )


def test_rows_differing_between_before_records_leave_the_comparison(
    tmp_path: Path,
) -> None:
    before = [_row(JSON_ARGS, stdout="a\n", exit_code=0), _row(JSON_ARGS, n=1)]
    again = [_row(JSON_ARGS, stdout="b\n", exit_code=0), _row(JSON_ARGS, n=1)]
    after = [_row(JSON_ARGS, stdout="c\n", exit_code=0), _row(JSON_ARGS, n=1)]
    result = _compare(tmp_path, before, after, before_again=again)
    assert result.returncode == 0
    assert _counts(result.stdout) == _expected_counts(같음=1, 비결정=1)
    assert f"# 비결정 행 (1)\n- {NODE}#0 exit=0/0 args={JSON_ARGS}\n" in result.stdout


@pytest.mark.parametrize(
    ("exit_code_again", "covered", "failures", "overlapping", "exit_code"),
    [
        pytest.param(1, [f"{NODE}#0"], 1, 1, 1, id="failure-on-moved-line"),
        pytest.param(1, [f"{NODE}#1"], 1, 0, 0, id="failure-elsewhere"),
        pytest.param(0, [f"{NODE}#0"], 0, 0, 0, id="success-on-moved-line"),
    ],
)
def test_nondeterministic_failure_on_a_moved_line_fails(
    tmp_path: Path,
    exit_code_again: int,
    covered: list[str],
    failures: int,
    overlapping: int,
    exit_code: int,
) -> None:
    before = [_row(JSON_ARGS, stdout="a\n", exit_code=0), _row(JSON_ARGS, n=1)]
    again = [
        _row(JSON_ARGS, stdout="b\n", exit_code=exit_code_again),
        _row(JSON_ARGS, n=1),
    ]
    result = _compare(tmp_path, before, before, before_again=again, covered=covered)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(
        같음=1,
        비결정=1,
        **{
            "비결정 실패 행": failures,
            "비결정 실패 행(옮기는 줄을 지남)": overlapping,
        },
    )


@pytest.mark.parametrize(
    ("intended", "expected", "exit_code"),
    [
        pytest.param(f"{NODE}#0", "의도한 동작 변경", 0, id="named"),
        pytest.param(f"{NODE}#1", "다름", 1, id="other-row"),
    ],
)
def test_intended_rows_are_named(
    tmp_path: Path, intended: str, expected: str, exit_code: int
) -> None:
    before = [_row(JSON_ARGS, stdout="a\n", exit_code=0)]
    after = [_row(JSON_ARGS, stdout="b\n", exit_code=1)]
    result = _compare(tmp_path, before, after, "--intended", intended)
    assert result.returncode == exit_code
    assert _counts(result.stdout) == _expected_counts(**{expected: 1})


@pytest.mark.parametrize(
    "content",
    [pytest.param("", id="empty"), pytest.param("{not json\n", id="malformed")],
)
def test_bad_input_exits_2(tmp_path: Path, content: str) -> None:
    good = _write(tmp_path / "good.jsonl", [_row(JSON_ARGS)])
    bad = tmp_path / "bad.jsonl"
    bad.write_text(content, encoding="utf-8")
    covered = tmp_path / "covered.json"
    covered.write_text("[]", encoding="utf-8")
    result = _run("compare", str(bad), good, good, "--covered", str(covered))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")


_COMMAND_SOURCE = """\
def run(fmt, bad):
    if bad:
        fmt.error("x", code="X")
        raise SystemExit(1)
"""


def _coverage(tmp_path: Path, measured: Path, contexts: list[str]) -> str:
    data = coverage.CoverageData(basename=str(tmp_path / "cov"))
    for context in contexts:
        data.set_context(context)
        data.add_lines({str(measured.resolve()): [3, 4]})
    data.write()
    return str(tmp_path / "cov")


@pytest.mark.parametrize(
    ("contexts", "exit_code", "error_state"),
    [
        pytest.param([f"{NODE}#0", f"{NODE}#1"], 0, "ok", id="both-modes"),
        pytest.param([f"{NODE}#0"], 1, "없음: text", id="json-only"),
    ],
)
def test_cover_counts_lines_by_mode(
    tmp_path: Path, contexts: list[str], exit_code: int, error_state: str
) -> None:
    source = tmp_path / "command.py"
    source.write_text(_COMMAND_SOURCE, encoding="utf-8")
    records = _write(tmp_path / "rec.jsonl", [_row(JSON_ARGS), _row(TEXT_ARGS, n=1)])
    data = _coverage(tmp_path, source, contexts)
    out = tmp_path / "covered.json"
    result = _run("cover", data, records, str(source), "--covered-out", str(out))
    assert result.returncode == exit_code, result.stderr
    assert result.stdout == (
        "# 덮개 (줄, 모드)\n"
        f"{source}:3 error {error_state}\n"
        f"{source}:4 exit {error_state}\n"
        "\n"
        "옮기는 줄: 2\n"
        "기록이 지난 줄(json): 2\n"
        f"기록이 지난 줄(text): {2 if exit_code == 0 else 0}\n"
    )
    assert json.loads(out.read_text(encoding="utf-8")) == contexts


@pytest.mark.parametrize(
    ("measured_name", "exit_code"),
    [
        pytest.param("command.py", 0, id="measured"),
        pytest.param("elsewhere.py", 2, id="not-measured"),
    ],
)
def test_cover_file_outside_the_data_is_an_input_error(
    tmp_path: Path, measured_name: str, exit_code: int
) -> None:
    source = tmp_path / "command.py"
    source.write_text(_COMMAND_SOURCE, encoding="utf-8")
    records = _write(tmp_path / "rec.jsonl", [_row(JSON_ARGS), _row(TEXT_ARGS, n=1)])
    data = _coverage(tmp_path, tmp_path / measured_name, [f"{NODE}#0", f"{NODE}#1"])
    result = _run("cover", data, records, str(source))
    assert result.returncode == exit_code, result.stdout + result.stderr
    if exit_code == 2:
        assert result.stdout == ""
        assert result.stderr == f"error: {source}: not measured in {data}\n"
