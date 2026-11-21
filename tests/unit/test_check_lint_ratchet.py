"""Lint ratchet checker tests."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_lint_ratchet.py"
    spec = importlib.util.spec_from_file_location("check_lint_ratchet", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load lint ratchet: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

Capsys = pytest.CaptureFixture[str]
Runner = Callable[[str, Sequence[str], Path], subprocess.CompletedProcess[str]]

TOOLS = {"ruff": "0.17.6", "mypy": "2.4.1"}
VERSION_OUTPUT = {"ruff": "ruff 0.17.6\n", "mypy": "mypy 2.4.1 (compiled: yes)\n"}
A = "src/ante/a.py"
B = "src/ante/b.py"

CONTRACT_ARGS = {
    "ruff": (
        "check",
        "src/",
        "--select",
        "BLE001,ASYNC,S608,C901",
        "--config",
        "lint.mccabe.max-complexity = 10",
        "--output-format",
        "json",
        "--no-fix",
        "--no-cache",
        "--exit-zero",
        "--ignore-noqa",
    ),
    "mypy": (
        "--strict",
        "--platform",
        "linux",
        "--cache-dir",
        ".mypy_cache/strict",
        "--no-error-summary",
        "--no-pretty",
        "--no-color-output",
        "src/",
    ),
}
INSTALL_SENTENCES = (
    'uv pip install -e ".[dev]" 또는 python -m pip install -e ".[dev]"로 '
    "고정 버전을 설치한다.",
    "기준선은 그 커밋의 src/를 CI 환경에서 잰 값과 같아야 한다.",
    "버전을 올리는 PR이면 같은 PR에서 기준선을 다시 잰다.",
)
LOWER_TEXT = "기준선을 낮춘다(0이면 키를 지운다)"
MOVE_TEXT = "파일을 옮기거나 새로 만들었다면 기준선을 옮긴다"
MYPY_TEXT = "타입을 채우거나 좁힌다."


def _proc(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


class FakeRunner:
    def __init__(
        self,
        outputs: dict[str, subprocess.CompletedProcess[str]],
        versions: dict[str, str],
    ) -> None:
        self.outputs = outputs
        self.versions = versions
        self.calls: list[tuple[str, tuple[str, ...], Path]] = []

    def __call__(
        self, module: str, args: Sequence[str], root: Path
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((module, tuple(args), root))
        if tuple(args) == ("--version",):
            return _proc(0, self.versions[module])
        assert tuple(args) == CONTRACT_ARGS[module]
        return self.outputs[module]


def _fake(
    ruff: subprocess.CompletedProcess[str] | None = None,
    mypy: subprocess.CompletedProcess[str] | None = None,
    versions: dict[str, str] | None = None,
) -> FakeRunner:
    outputs = {"ruff": ruff or _proc(0, "[]"), "mypy": mypy or _proc(0)}
    return FakeRunner(outputs, VERSION_OUTPUT if versions is None else versions)


def _write_baseline(root: Path, data: object) -> None:
    path = root / "scripts" / "lint_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _baseline(
    ruff: dict[str, dict[str, int]] | None = None,
    mypy: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    return {"tools": dict(TOOLS), "ruff": ruff or {}, "mypy": mypy or {}}


def _ruff_json(root: Path, *items: tuple[str, str]) -> str:
    base = root.resolve()
    return json.dumps(
        [{"filename": str(base / path), "code": code} for path, code in items]
    )


def _mypy_text(*items: tuple[str, str]) -> str:
    return "".join(f"{path}:1: error: Message  [{code}]\n" for path, code in items)


def _run(root: Path, runner: Runner, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)], runner)
    captured = capsys.readouterr()
    if isinstance(runner, FakeRunner):
        assert all(call_root == root for _, _, call_root in runner.calls)
    output = captured.out + captured.err
    if code == 2:
        assert not any(
            line.startswith(("lint ratchet ok", "lint ratchet failed"))
            for line in output.splitlines()
        )
    return code, output


# ── 실행 방식 ──────────────────────────────────────────────


def test_tool_args_are_the_contract_literals() -> None:
    assert checker.RUFF_ARGS == CONTRACT_ARGS["ruff"]
    assert checker.MYPY_ARGS == CONTRACT_ARGS["mypy"]


@pytest.mark.parametrize("module", ["ruff", "mypy"])
def test_run_tool_uses_this_interpreter_in_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append((argv, kwargs))
        return _proc(0)

    monkeypatch.setattr(checker.subprocess, "run", fake_run)
    checker.run_tool(module, CONTRACT_ARGS[module], tmp_path)
    [(argv, kwargs)] = seen
    assert argv == [sys.executable, "-m", module, *CONTRACT_ARGS[module]]
    assert kwargs["cwd"] == tmp_path


def test_every_tool_call_runs_in_the_given_root(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _baseline())
    runner = _fake()
    code, _ = _run(tmp_path, runner, capsys)
    assert code == 0
    calls = [(module, args) for module, args, _ in runner.calls]
    assert set(calls[:2]) == {("ruff", ("--version",)), ("mypy", ("--version",))}
    assert set(calls[2:]) == {(name, args) for name, args in CONTRACT_ARGS.items()}
    assert len(calls) == 4
    assert {root for _, _, root in runner.calls} == {tmp_path}


def _run_ruff(
    tmp_path: Path, proc: subprocess.CompletedProcess[str], capsys: Capsys
) -> tuple[int, str]:
    _write_baseline(tmp_path, _baseline())
    return _run(tmp_path, _fake(ruff=proc), capsys)


def _run_mypy(
    tmp_path: Path, proc: subprocess.CompletedProcess[str], capsys: Capsys
) -> tuple[int, str]:
    _write_baseline(tmp_path, _baseline())
    return _run(tmp_path, _fake(mypy=proc), capsys)


# ── ruff 해석 ──────────────────────────────────────────────


def test_ruff_item_is_counted(tmp_path: Path) -> None:
    text = _ruff_json(tmp_path, (A, "BLE001"))
    assert checker.parse_ruff_json(text, tmp_path) == {A: {"BLE001": 1}}


def test_ruff_same_file_and_code_are_summed(tmp_path: Path) -> None:
    text = _ruff_json(tmp_path, (A, "C901"), (A, "C901"), (A, "S608"), (B, "C901"))
    assert checker.parse_ruff_json(text, tmp_path) == {
        A: {"C901": 2, "S608": 1},
        B: {"C901": 1},
    }


def test_ruff_realpath_under_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    text = json.dumps([{"filename": str(real.resolve() / A), "code": "BLE001"}])
    assert checker.parse_ruff_json(text, link) == {A: {"BLE001": 1}}


def test_ruff_relative_filename_is_under_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    root = tmp_path / "root"
    root.mkdir()
    text = json.dumps([{"filename": A, "code": "BLE001"}])
    assert checker.parse_ruff_json(text, root) == {A: {"BLE001": 1}}


def test_ruff_file_outside_root_is_error(tmp_path: Path, capsys: Capsys) -> None:
    root = tmp_path / "root"
    root.mkdir()
    text = json.dumps([{"filename": str(tmp_path / "other.py"), "code": "BLE001"}])
    code, output = _run_ruff(root, _proc(0, text), capsys)
    assert code == 2
    assert "outside" in output


@pytest.mark.parametrize(
    "item",
    [
        {"code": "invalid-syntax"},
        {"code": None},
        {},
        {"code": "ble001"},
        {"code": "BLE"},
        {"code": "001"},
        {"code": "BLE001 "},
    ],
    ids=[
        "invalid-syntax",
        "null",
        "missing",
        "lower",
        "no-digits",
        "no-letters",
        "space",
    ],
)
def test_ruff_item_without_rule_code_is_error(
    tmp_path: Path, capsys: Capsys, item: dict[str, object]
) -> None:
    text = json.dumps([{"filename": str(tmp_path.resolve() / A), **item}])
    code, output = _run_ruff(tmp_path, _proc(0, text), capsys)
    assert code == 2
    assert "rule code" in output


@pytest.mark.parametrize("text", ['{"filename": "x"}', "not json", ""])
def test_ruff_output_not_a_json_list_is_error(
    tmp_path: Path, capsys: Capsys, text: str
) -> None:
    code, _ = _run_ruff(tmp_path, _proc(0, text), capsys)
    assert code == 2


def test_ruff_nonzero_exit_is_error_whatever_the_output(
    tmp_path: Path, capsys: Capsys
) -> None:
    code, output = _run_ruff(tmp_path, _proc(1, "[]", "boom"), capsys)
    assert code == 2
    assert "ruff exited with 1" in output


def test_ruff_item_without_filename_is_error(tmp_path: Path, capsys: Capsys) -> None:
    code, output = _run_ruff(tmp_path, _proc(0, '[{"code": "BLE001"}]'), capsys)
    assert code == 2
    assert "filename" in output


# ── mypy 해석 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (f"{A}:3: error: Bad  [type-arg]", {A: {"type-arg": 1}}),
        (f"{A}:3:7: error: Bad  [type-arg]", {A: {"type-arg": 1}}),
        (f"{A}:3: note: See docs", {}),
        (f"{A}:3: warning: Unused section", {}),
    ],
    ids=["error", "error-with-column", "note", "warning"],
)
def test_mypy_line_by_severity(line: str, expected: dict[str, dict[str, int]]) -> None:
    returncode = 1 if expected else 0
    assert checker.parse_mypy(line + "\n", returncode) == expected


def test_mypy_message_with_brackets() -> None:
    line = f'{A}:5: error: Missing type arguments for "dict[str]" [x]  [type-arg]'
    assert checker.parse_mypy(line, 1) == {A: {"type-arg": 1}}


@pytest.mark.parametrize(
    ("tail", "counted"),
    [
        ("  [type-arg]", True),
        (" [type-arg]", False),
        ("[type-arg]", False),
        ("  [Type-Arg]", False),
        ("  [type_arg]", False),
        ("  [type-arg] ", False),
    ],
    ids=["two-spaces", "one-space", "no-space", "upper", "underscore", "trailing"],
)
def test_mypy_code_tail_is_two_spaces_and_code(
    tmp_path: Path, capsys: Capsys, tail: str, counted: bool
) -> None:
    _write_baseline(tmp_path, _baseline(mypy={A: {"type-arg": 1}}))
    proc = _proc(1, f"{A}:5: error: Bad thing{tail}\n")
    code, output = _run(tmp_path, _fake(mypy=proc), capsys)
    assert code == (0 if counted else 2), output


def test_mypy_path_is_the_line_prefix_as_printed() -> None:
    text = f"./{A}:1: error: Bad  [misc]\n"
    assert checker.parse_mypy(text, 1) == {f"./{A}": {"misc": 1}}


def test_mypy_blank_lines_are_skipped() -> None:
    text = f"\n{A}:1: error: Bad  [misc]\n\n{A}:2: note: n\n\n"
    assert checker.parse_mypy(text, 1) == {A: {"misc": 1}}


def test_mypy_error_without_code_is_error(tmp_path: Path, capsys: Capsys) -> None:
    code, output = _run_mypy(tmp_path, _proc(1, f"{A}:5: error: Bad thing\n"), capsys)
    assert code == 2
    assert "without an error code" in output


def test_mypy_unmatched_line_is_error(tmp_path: Path, capsys: Capsys) -> None:
    code, output = _run_mypy(tmp_path, _proc(0, "Found 3 errors in 1 file\n"), capsys)
    assert code == 2
    assert "unexpected mypy output line" in output


@pytest.mark.parametrize(
    ("returncode", "text", "ok"),
    [
        (0, "", True),
        (1, f"{A}:1: error: Bad  [misc]\n", True),
        (0, f"{A}:1: error: Bad  [misc]\n", False),
        (1, f"{A}:1: note: Only a note\n", False),
    ],
    ids=["0-none", "1-some", "0-some", "1-none"],
)
def test_mypy_exit_code_must_agree_with_errors(
    returncode: int, text: str, ok: bool
) -> None:
    if ok:
        checker.parse_mypy(text, returncode)
    else:
        with pytest.raises(checker.CheckError):
            checker.parse_mypy(text, returncode)


def test_mypy_exit_two_is_error(tmp_path: Path, capsys: Capsys) -> None:
    code, output = _run_mypy(tmp_path, _proc(2, "", "fatal"), capsys)
    assert code == 2
    assert "mypy exited with 2" in output


def test_mypy_stderr_is_printed_not_parsed(tmp_path: Path, capsys: Capsys) -> None:
    proc = _proc(0, "", "Unrecognized option: --frobnicate\n")
    code, output = _run_mypy(tmp_path, proc, capsys)
    assert code == 0
    assert output.splitlines() == [_ok(0, 0), "Unrecognized option: --frobnicate"]


def test_mypy_duplicate_module_line_is_error(tmp_path: Path, capsys: Capsys) -> None:
    line = f'{A}: error: Duplicate module named "ante.a" (also at "x/{A}")\n'
    code, output = _run_mypy(tmp_path, _proc(1, line), capsys)
    assert code == 2
    assert "unexpected mypy output line" in output


# ── 판정 ───────────────────────────────────────────────────

HEADER = "lint ratchet failed against scripts/lint_baseline.json:"
DEPS_HEADER = "installed [project].dependencies:"
RUFF_TEXT = {
    "BLE001": "예외를 좁히거나 다시 던진다. 판정 값을 기본값으로 채우지 않는다.",
    "ASYNC240": "asyncio.to_thread나 비동기 API를 쓴다.",
    "ASYNC109": "asyncio.to_thread나 비동기 API를 쓴다.",
    "S608": "자리표시자를 쓴다.",
    "C901": "함수를 나눈다.",
}


def _ok(ruff: int, mypy: int) -> str:
    return (
        f"lint ratchet ok: {ruff} ruff findings, {mypy} mypy --strict errors "
        "(baseline scripts/lint_baseline.json)"
    )


def _alt(kind: str, code: str) -> str:
    return f"  대안: {MYPY_TEXT if kind == 'mypy' else RUFF_TEXT[code]}"


LOWER_LINE = f"  {LOWER_TEXT}."
MOVE_LINE = f"  {MOVE_TEXT}."

CASES = {
    "match": ({A: {"X1": 2}}, {A: {"X1": 2}}),
    "grew-existing-key": ({A: {"X1": 3}}, {A: {"X1": 2}}),
    "grew-new-file": ({A: {"X1": 2}, B: {"X1": 1}}, {A: {"X1": 2}}),
    "grew-new-code": ({A: {"X1": 2, "X2": 1}}, {A: {"X1": 2}}),
    "lowered-value": ({A: {"X1": 1}}, {A: {"X1": 2}}),
    "lowered-to-zero": ({A: {"X1": 2}}, {A: {"X1": 2}, B: {"X1": 1}}),
    "moved-file": ({B: {"X1": 2}}, {A: {"X1": 2}}),
    "moved-code": ({A: {"X2": 2}}, {A: {"X1": 2}}),
}

GREW = "grew"
GREW_NEW_FILE = "grew-new-file"
LOWERED = "lowered"
DIFF_ROWS = {
    "grew-existing-key": [(A, "X1", 3, 2, GREW)],
    "grew-new-file": [(B, "X1", 1, 0, GREW_NEW_FILE)],
    "grew-new-code": [(A, "X2", 1, 0, GREW)],
    "lowered-value": [(A, "X1", 1, 2, LOWERED)],
    "lowered-to-zero": [(B, "X1", 0, 1, LOWERED)],
    "moved-file": [(A, "X1", 0, 2, LOWERED), (B, "X1", 2, 0, GREW_NEW_FILE)],
    "moved-code": [(A, "X1", 0, 2, LOWERED), (A, "X2", 2, 0, GREW)],
}

CODES = {
    "ruff": {"X1": "BLE001", "X2": "C901"},
    "mypy": {"X1": "type-arg", "X2": "no-untyped-def"},
}


def _rename(counts: dict[str, dict[str, int]], kind: str) -> dict[str, dict[str, int]]:
    return {
        path: {CODES[kind][key]: value for key, value in codes.items()}
        for path, codes in counts.items()
    }


def _expand(counts: dict[str, dict[str, int]]) -> list[tuple[str, str]]:
    return [
        (path, code)
        for path, codes in counts.items()
        for code, count in codes.items()
        for _ in range(count)
    ]


def _expected_rows(kind: str, case: str) -> list[str]:
    lines: list[str] = []
    rows = sorted(DIFF_ROWS[case], key=lambda row: (row[0], CODES[kind][row[1]]))
    for path, key, got, want, change in rows:
        code = CODES[kind][key]
        lines.append(
            f"{kind}\t{path}\t{code}: actual {got}, baseline {want} ({got - want:+d})"
        )
        if change == LOWERED:
            lines.append(LOWER_LINE)
        else:
            lines.append(_alt(kind, code))
            if change == GREW_NEW_FILE:
                lines.append(MOVE_LINE)
    return lines


def _write_pyproject(root: Path, dependencies: Sequence[str] = ()) -> None:
    (root / "pyproject.toml").write_text(
        f"[project]\ndependencies = {json.dumps(list(dependencies))}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("kind", ["ruff", "mypy"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_judge_table(tmp_path: Path, capsys: Capsys, kind: str, case: str) -> None:
    _write_pyproject(tmp_path)
    actual, baseline = (_rename(counts, kind) for counts in CASES[case])
    if kind == "ruff":
        runner = _fake(ruff=_proc(0, _ruff_json(tmp_path, *_expand(actual))))
        _write_baseline(tmp_path, _baseline(ruff=baseline))
    else:
        runner = _fake(mypy=_proc(1, _mypy_text(*_expand(actual))))
        _write_baseline(tmp_path, _baseline(mypy=baseline))
    code, output = _run(tmp_path, runner, capsys)
    if case == "match":
        assert code == 0
        assert output.splitlines() == [_ok(2, 0) if kind == "ruff" else _ok(0, 2)]
        return
    assert code == 1
    expected = [HEADER, *_expected_rows(kind, case)]
    if kind == "mypy":
        expected.append(DEPS_HEADER)
    assert output.splitlines() == expected


def _fix_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    def version(name: str) -> str:
        if name == "pytest":
            return "8.0.0"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(checker.importlib.metadata, "version", version)


def test_ruff_and_mypy_mismatch_together(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fix_versions(monkeypatch)
    _write_pyproject(tmp_path, ["pytest>=8.0", "no-such-dist-xyz<2"])
    _write_baseline(tmp_path, _baseline(mypy={A: {"type-arg": 2}}))
    runner = _fake(
        ruff=_proc(0, _ruff_json(tmp_path, (A, "S608"))),
        mypy=_proc(1, _mypy_text((A, "type-arg"))),
    )
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    assert output.splitlines() == [
        HEADER,
        f"ruff\t{A}\tS608: actual 1, baseline 0 (+1)",
        "  대안: 자리표시자를 쓴다.",
        MOVE_LINE,
        f"mypy\t{A}\ttype-arg: actual 1, baseline 2 (-1)",
        LOWER_LINE,
        DEPS_HEADER,
        "  pytest==8.0.0",
        "  no-such-dist-xyz==not installed",
    ]


@pytest.mark.parametrize("code", sorted(RUFF_TEXT))
def test_ruff_alternative_per_rule(tmp_path: Path, capsys: Capsys, code: str) -> None:
    _write_pyproject(tmp_path, ["pytest>=8.0"])
    _write_baseline(tmp_path, _baseline(ruff={A: {code: 1}}))
    runner = _fake(ruff=_proc(0, _ruff_json(tmp_path, (A, code), (A, code))))
    exit_code, output = _run(tmp_path, runner, capsys)
    assert exit_code == 1
    assert output.splitlines() == [
        HEADER,
        f"ruff\t{A}\t{code}: actual 2, baseline 1 (+1)",
        f"  대안: {RUFF_TEXT[code]}",
    ]


def test_mypy_mismatch_prints_dependency_versions(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fix_versions(monkeypatch)
    _write_pyproject(tmp_path, ["pytest>=8.0", "no-such-dist-xyz<2"])
    _write_baseline(tmp_path, _baseline(mypy={A: {"type-arg": 1}}))
    runner = _fake(mypy=_proc(1, _mypy_text((A, "type-arg"), (A, "type-arg"))))
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    assert output.splitlines() == [
        HEADER,
        f"mypy\t{A}\ttype-arg: actual 2, baseline 1 (+1)",
        f"  대안: {MYPY_TEXT}",
        DEPS_HEADER,
        "  pytest==8.0.0",
        "  no-such-dist-xyz==not installed",
    ]


def test_unreadable_pyproject_is_reported_not_fatal(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, _baseline())
    runner = _fake(mypy=_proc(1, _mypy_text((A, "type-arg"))))
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    lines = output.splitlines()
    assert lines[:-1] == [
        HEADER,
        f"mypy\t{A}\ttype-arg: actual 1, baseline 0 (+1)",
        f"  대안: {MYPY_TEXT}",
        MOVE_LINE,
        DEPS_HEADER,
    ]
    assert lines[-1].startswith(
        "  cannot read [project].dependencies: FileNotFoundError"
    )


def test_ruff_only_mismatch_omits_dependency_versions(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_pyproject(tmp_path, ["pytest>=8.0"])
    _write_baseline(tmp_path, _baseline(mypy={A: {"type-arg": 1}}))
    runner = _fake(
        ruff=_proc(0, _ruff_json(tmp_path, (A, "C901"))),
        mypy=_proc(1, _mypy_text((A, "type-arg"))),
    )
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    assert output.splitlines() == [
        HEADER,
        f"ruff\t{A}\tC901: actual 1, baseline 0 (+1)",
        "  대안: 함수를 나눈다.",
        MOVE_LINE,
    ]


# ── 도구 버전 ──────────────────────────────────────────────


def _version_error(module: str, installed: str, wanted: str) -> list[str]:
    return [
        f"{module} {installed} is installed, baseline needs {wanted}",
        *INSTALL_SENTENCES,
    ]


@pytest.mark.parametrize(
    ("module", "version"),
    [
        ("ruff", "9.9.9"),
        ("ruff", "0.17.7"),
        ("ruff", "0.17.60"),
        ("ruff", "0.17"),
        ("ruff", "0.17.6rc1"),
        ("mypy", "9.9.9"),
        ("mypy", "2.4.2"),
        ("mypy", "2.4.10"),
        ("mypy", "2.4"),
        ("mypy", "2.4.1.dev0"),
    ],
)
def test_version_must_match_exactly(
    tmp_path: Path, capsys: Capsys, module: str, version: str
) -> None:
    _write_baseline(tmp_path, _baseline())
    versions = {**VERSION_OUTPUT, module: f"{module} {version}\n"}
    runner = _fake(versions=versions)
    code, output = _run(tmp_path, runner, capsys)
    assert code == 2
    assert output.splitlines() == _version_error(module, version, TOOLS[module])
    assert all(args == ("--version",) for _, args, _ in runner.calls)


OTHER_TOOLS = {"ruff": "0.99.1", "mypy": "9.8.7"}
OTHER_VERSION_OUTPUT = {"ruff": "ruff 0.99.1\n", "mypy": "mypy 9.8.7 (compiled: no)\n"}


def test_version_is_compared_with_baseline_tools(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, {**_baseline(), "tools": dict(OTHER_TOOLS)})
    code, output = _run(tmp_path, _fake(versions=OTHER_VERSION_OUTPUT), capsys)
    assert code == 0
    assert output.splitlines() == [_ok(0, 0)]


@pytest.mark.parametrize("module", ["ruff", "mypy"])
def test_pinned_version_fails_against_other_baseline_tools(
    tmp_path: Path, capsys: Capsys, module: str
) -> None:
    _write_baseline(tmp_path, {**_baseline(), "tools": dict(OTHER_TOOLS)})
    versions = {**OTHER_VERSION_OUTPUT, module: VERSION_OUTPUT[module]}
    runner = _fake(versions=versions)
    code, output = _run(tmp_path, runner, capsys)
    assert code == 2
    assert output.splitlines() == _version_error(
        module, TOOLS[module], OTHER_TOOLS[module]
    )


def test_version_command_failure_is_error(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _baseline())

    def runner(
        module: str, args: Sequence[str], root: Path
    ) -> subprocess.CompletedProcess[str]:
        return _proc(1, VERSION_OUTPUT[module], "No module named x")

    code, output = _run(tmp_path, runner, capsys)
    assert code == 2
    assert output.splitlines()[0].startswith("cannot read ruff version (exit 1)")
    assert output.splitlines()[-3:] == list(INSTALL_SENTENCES)


@pytest.mark.parametrize("shown", ["ruff\n", ""])
def test_version_without_second_word_is_error(
    tmp_path: Path, capsys: Capsys, shown: str
) -> None:
    _write_baseline(tmp_path, _baseline())
    versions = {**VERSION_OUTPUT, "ruff": shown}
    code, output = _run(tmp_path, _fake(versions=versions), capsys)
    assert code == 2
    assert output.splitlines() == [
        f"cannot read ruff version (exit 0): {shown.strip()!r}",
        *INSTALL_SENTENCES,
    ]


# ── 기준선 형식 ────────────────────────────────────────────


def _malformed() -> list[object]:
    good = _baseline(ruff={A: {"BLE001": 1}})
    cases: list[object] = [
        [],
        {k: v for k, v in good.items() if k != "ruff"},
        {k: v for k, v in good.items() if k != "tools"},
        {**good, "extra": {}},
        {**good, "tools": {"ruff": "0.17.6"}},
        {**good, "tools": {**TOOLS, "black": "1"}},
        {**good, "tools": {"ruff": "0.17.6", "mypy": 2.4}},
        {**good, "tools": "0.17.6"},
        {**good, "ruff": []},
        {**good, "ruff": {A: {}}},
        {**good, "ruff": {A: 3}},
    ]
    for bad in (0, -1, True, 1.0, "1", None):
        cases.append({**good, "ruff": {A: {"BLE001": bad}}})
        cases.append({**good, "mypy": {A: {"type-arg": bad}}})
    return cases


@pytest.mark.parametrize("data", _malformed())
def test_malformed_baseline_is_error(
    tmp_path: Path, capsys: Capsys, data: object
) -> None:
    _write_baseline(tmp_path, data)
    code, output = _run(tmp_path, _fake(), capsys)
    assert code == 2
    assert "lint_baseline.json" in output


def test_missing_baseline_is_error(tmp_path: Path, capsys: Capsys) -> None:
    code, output = _run(tmp_path, _fake(), capsys)
    assert code == 2
    assert "baseline file not found" in output


def test_broken_json_baseline_is_error(tmp_path: Path, capsys: Capsys) -> None:
    path = tmp_path / "scripts" / "lint_baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    code, output = _run(tmp_path, _fake(), capsys)
    assert code == 2
    assert "not valid JSON" in output


def test_measurement_exception_is_error(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _baseline())

    def runner(
        module: str, args: Sequence[str], root: Path
    ) -> subprocess.CompletedProcess[str]:
        if tuple(args) == ("--version",):
            return _proc(0, VERSION_OUTPUT[module])
        raise RuntimeError("tool crashed")

    code, output = _run(tmp_path, runner, capsys)
    assert code == 2
    assert "RuntimeError: tool crashed" in output


def test_pyproject_pins_match_baseline_tools() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        dev = tomllib.load(handle)["project"]["optional-dependencies"]["dev"]
    baseline = json.loads(
        (REPO_ROOT / "scripts" / "lint_baseline.json").read_text(encoding="utf-8")
    )
    pins = {
        name: version
        for name, version in (
            requirement.split("==", 1) for requirement in dev if "==" in requirement
        )
    }
    assert pins == baseline["tools"]
