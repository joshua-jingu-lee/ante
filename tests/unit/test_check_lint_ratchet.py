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
    return code, captured.out + captured.err


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
    assert "Unrecognized option: --frobnicate" in output


def test_mypy_duplicate_module_line_is_error(tmp_path: Path, capsys: Capsys) -> None:
    line = f'{A}: error: Duplicate module named "ante.a" (also at "x/{A}")\n'
    code, output = _run_mypy(tmp_path, _proc(1, line), capsys)
    assert code == 2
    assert "unexpected mypy output line" in output


# ── 판정 ───────────────────────────────────────────────────

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


DIFF_ROWS = {
    "grew-existing-key": [(A, "X1", 3, 2)],
    "grew-new-file": [(B, "X1", 1, 0)],
    "grew-new-code": [(A, "X2", 1, 0)],
    "lowered-value": [(A, "X1", 1, 2)],
    "lowered-to-zero": [(B, "X1", 0, 1)],
    "moved-file": [(A, "X1", 0, 2), (B, "X1", 2, 0)],
    "moved-code": [(A, "X1", 0, 2), (A, "X2", 2, 0)],
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


def _judge_output(
    tmp_path: Path, capsys: Capsys, kind: str, case: str
) -> tuple[int, str]:
    actual, baseline = (_rename(counts, kind) for counts in CASES[case])
    if kind == "ruff":
        runner = _fake(ruff=_proc(0, _ruff_json(tmp_path, *_expand(actual))))
        _write_baseline(tmp_path, _baseline(ruff=baseline))
    else:
        runner = _fake(mypy=_proc(1, _mypy_text(*_expand(actual))))
        _write_baseline(tmp_path, _baseline(mypy=baseline))
    return _run(tmp_path, runner, capsys)


@pytest.mark.parametrize("kind", ["ruff", "mypy"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_judge_table(tmp_path: Path, capsys: Capsys, kind: str, case: str) -> None:
    code, output = _judge_output(tmp_path, capsys, kind, case)
    if case == "match":
        assert code == 0, output
        assert "lint ratchet ok" in output
        return
    assert code == 1, output
    rows = {line for line in output.splitlines() if line.startswith(f"{kind}\t")}
    assert rows == {
        f"{kind}\t{path}\t{CODES[kind][key]}: actual {got}, baseline {want} "
        f"({got - want:+d})"
        for path, key, got, want in DIFF_ROWS[case]
    }
    if case.startswith("grew"):
        assert "  대안: " in output
        if kind == "mypy":
            assert f"  대안: {MYPY_TEXT}" in output
    assert (LOWER_TEXT in output) == (
        case.startswith("lowered") or case.startswith("moved")
    )
    assert (MOVE_TEXT in output) == (case in ("grew-new-file", "moved-file"))


@pytest.mark.parametrize(
    ("code", "alternative"),
    [
        ("BLE001", "예외를 좁히거나 다시 던진다. 판정 값을 기본값으로 채우지 않는다."),
        ("ASYNC240", "asyncio.to_thread나 비동기 API를 쓴다."),
        ("ASYNC109", "asyncio.to_thread나 비동기 API를 쓴다."),
        ("S608", "자리표시자를 쓴다."),
        ("C901", "함수를 나눈다."),
    ],
)
def test_ruff_alternative_per_rule(
    tmp_path: Path, capsys: Capsys, code: str, alternative: str
) -> None:
    _write_baseline(tmp_path, _baseline())
    runner = _fake(ruff=_proc(0, _ruff_json(tmp_path, (A, code))))
    exit_code, output = _run(tmp_path, runner, capsys)
    assert exit_code == 1
    assert f"  대안: {alternative}" in output


def _write_pyproject(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pytest>=8.0", "no-such-dist-xyz<2"]\n',
        encoding="utf-8",
    )


def test_mypy_mismatch_prints_dependency_versions(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_pyproject(tmp_path)
    _write_baseline(tmp_path, _baseline())
    runner = _fake(mypy=_proc(1, _mypy_text((A, "type-arg"))))
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    assert f"pytest=={importlib.metadata.version('pytest')}" in output
    assert "no-such-dist-xyz==not installed" in output


def test_ruff_only_mismatch_omits_dependency_versions(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_pyproject(tmp_path)
    _write_baseline(tmp_path, _baseline())
    runner = _fake(ruff=_proc(0, _ruff_json(tmp_path, (A, "C901"))))
    code, output = _run(tmp_path, runner, capsys)
    assert code == 1
    assert "pytest==" not in output
    assert "dependencies" not in output


# ── 도구 버전 ──────────────────────────────────────────────


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
    assert f"{module} {version} is installed" in output
    for sentence in INSTALL_SENTENCES:
        assert sentence in output
    assert 'uv pip install -e ".[dev]"' in output
    assert 'python -m pip install -e ".[dev]"' in output
    assert all(args == ("--version",) for _, args, _ in runner.calls)


def test_version_command_failure_is_error(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _baseline())

    def runner(
        module: str, args: Sequence[str], root: Path
    ) -> subprocess.CompletedProcess[str]:
        return _proc(1, VERSION_OUTPUT[module], "No module named x")

    code, output = _run(tmp_path, runner, capsys)
    assert code == 2
    assert "cannot read ruff version" in output


@pytest.mark.parametrize("shown", ["ruff\n", ""])
def test_version_without_second_word_is_error(
    tmp_path: Path, capsys: Capsys, shown: str
) -> None:
    _write_baseline(tmp_path, _baseline())
    versions = {**VERSION_OUTPUT, "ruff": shown}
    code, output = _run(tmp_path, _fake(versions=versions), capsys)
    assert code == 2
    assert "cannot read ruff version" in output
    for sentence in INSTALL_SENTENCES:
        assert sentence in output


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
