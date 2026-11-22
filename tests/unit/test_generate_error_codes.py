"""``scripts/generate_error_codes.py``의 표기·결정성·``--check`` 테스트.

표기 규칙은 등록하지 않는 픽스처 ``ErrorSpec``으로 잠그고, 생성 문서가
레지스트리와 어긋나는지는 ``--check``와 커밋된 문서 비교가 판정한다.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from ante.contracts import error_registry
from ante.contracts.errors import ErrorSpec

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _ROOT / "scripts" / "generate_error_codes.py"
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_CHECK_COMMAND = "python scripts/generate_error_codes.py --check"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("generate_error_codes", _SCRIPT_PATH)


class _FixtureError(Exception):
    pass


class _OtherFixtureError(Exception):
    pass


_PLAIN = ErrorSpec(code="FIXTURE_PLAIN", category="validation")
_DESCRIBED = ErrorSpec(
    code="FIXTURE_DESCRIBED",
    category="not_found",
    description="`--flag` 값이 없음",
)
_SHARED_A = ErrorSpec(code="FIXTURE_SHARED", category="internal")
_SHARED_B = ErrorSpec(code="FIXTURE_SHARED", category="internal")


def _rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("| `")]


def test_description_defaults_to_empty_and_is_last_field() -> None:
    spec = ErrorSpec("X", "internal", 2, True, "m")
    assert spec.description == ""
    assert (spec.exit_code, spec.retryable, spec.default_message) == (2, True, "m")


def test_rows_render_registry_values() -> None:
    text = gen.render(
        [_PLAIN, _DESCRIBED, _SHARED_A, _SHARED_B],
        {_FixtureError: _DESCRIBED, _OtherFixtureError: _SHARED_B},
    )
    fixture = f"{__name__}._FixtureError"
    other = f"{__name__}._OtherFixtureError"
    assert _rows(text) == [
        f"| `FIXTURE_DESCRIBED` | `not_found` | 1 | `{fixture}` | `--flag` 값이 없음 |",
        "| `FIXTURE_PLAIN` | `validation` | 1 | — | — |",
        f"| `FIXTURE_SHARED` | `internal` | 1 | `{other}` | — |",
    ]


def test_classes_of_one_code_are_sorted_by_path() -> None:
    text = gen.render(
        [_SHARED_A, _SHARED_B],
        {_OtherFixtureError: _SHARED_A, _FixtureError: _SHARED_B},
    )
    fixture = f"`{__name__}._FixtureError`"
    other = f"`{__name__}._OtherFixtureError`"
    assert _rows(text) == [
        f"| `FIXTURE_SHARED` | `internal` | 1 | {fixture}<br>{other} | — |"
    ]


@pytest.mark.parametrize(
    "spec",
    [
        ErrorSpec(code="BAD`CODE", category="internal"),
        ErrorSpec(code="BAD|CODE", category="internal"),
        ErrorSpec(code="BAD\nCODE", category="internal"),
        ErrorSpec(code="FIXTURE", category="internal", description="a|b"),
        ErrorSpec(code="FIXTURE", category="internal", description="a\nb"),
        ErrorSpec(code="FIXTURE", category="internal", description="a\rb"),
        ErrorSpec(code="FIXTURE", category="internal", description="`a"),
    ],
)
def test_unknown_marks_fail(spec: ErrorSpec) -> None:
    with pytest.raises(gen.UnsupportedValueError):
        gen.render([spec], {})


def test_unknown_mark_in_class_path_fails() -> None:
    bad = type("Bad|Error", (Exception,), {})
    with pytest.raises(gen.UnsupportedValueError):
        gen.render([_PLAIN], {bad: _PLAIN})


@pytest.mark.parametrize(
    "other",
    [
        ErrorSpec(code="FIXTURE_SHARED", category="validation"),
        ErrorSpec(code="FIXTURE_SHARED", category="internal", exit_code=2),
        ErrorSpec(code="FIXTURE_SHARED", category="internal", description="뜻"),
    ],
)
def test_specs_of_one_code_must_agree(other: ErrorSpec) -> None:
    with pytest.raises(gen.UnsupportedValueError):
        gen.render([_SHARED_A, other], {})


def test_mapping_to_unregistered_code_fails() -> None:
    with pytest.raises(gen.UnsupportedValueError):
        gen.render([_PLAIN], {_FixtureError: _DESCRIBED})


def test_render_is_independent_of_input_order() -> None:
    specs = gen.registry_specs(vars(error_registry))
    mapping = dict(error_registry.EXCEPTION_TO_SPEC)
    forward = gen.render(specs, mapping)
    backward = gen.render(list(reversed(specs)), dict(reversed(list(mapping.items()))))
    assert forward == backward


def _ratchet_registered_codes() -> set[str]:
    ratchet = _load("check_entry_ratchet", _ROOT / "scripts" / "check_entry_ratchet.py")
    source = (_ROOT / "src" / "ante" / "contracts" / "error_registry.py").read_text(
        encoding="utf-8"
    )
    codes: set[str] = ratchet.registered_codes(ast.parse(source))
    return codes


def test_one_row_per_code_the_ratchet_counts_as_registered() -> None:
    rows = _rows(gen.render_error_codes())
    codes = [row.split(" | ")[0].removeprefix("| `").removesuffix("`") for row in rows]
    assert len(codes) == len(set(codes))
    assert set(codes) == _ratchet_registered_codes()


def test_every_mapped_class_appears_in_its_row() -> None:
    text = gen.render_error_codes()
    for cls, spec in error_registry.EXCEPTION_TO_SPEC.items():
        row = next(r for r in _rows(text) if r.startswith(f"| `{spec.code}` |"))
        assert f"`{cls.__module__}.{cls.__qualname__}`" in row


def test_committed_document_is_current() -> None:
    committed = gen.DEFAULT_OUTPUT.read_text(encoding="utf-8")
    assert gen.render_error_codes() == committed


def _run(
    *args: str, home: Path, cwd: Path = _ROOT, hashseed: str = "0"
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "ANTE_CONFIG_DIR"}
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = hashseed
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_output_is_byte_identical_across_hash_seed_and_cwd(tmp_path: Path) -> None:
    first = _run("--stdout", home=tmp_path, hashseed="0")
    second = _run("--stdout", home=tmp_path, cwd=tmp_path, hashseed="12345")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert first.stdout == gen.render_error_codes()


def test_check_exit_codes(tmp_path: Path) -> None:
    output = tmp_path / "error-codes.md"
    assert _run("--output", str(output), home=tmp_path).returncode == 0
    assert _run("--check", "--output", str(output), home=tmp_path).returncode == 0
    lines = output.read_text(encoding="utf-8").splitlines(keepends=True)
    row = next(i for i, line in enumerate(lines) if line.startswith("| `"))
    lines[row] = lines[row].replace(" | 1 | ", " | 2 | ", 1)
    output.write_text("".join(lines), encoding="utf-8")
    stale = _run("--check", "--output", str(output), home=tmp_path)
    assert stale.returncode == 1
    assert "is stale." in stale.stdout
    missing = _run("--check", "--output", str(tmp_path / "absent.md"), home=tmp_path)
    assert missing.returncode == 1


def test_ci_lint_job_runs_the_check() -> None:
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    runs = [
        str(step.get("run", ""))
        for step in workflow["jobs"]["lint"]["steps"]
        if step.get("name") == "Generated artifact sync check"
    ]
    assert len(runs) == 1
    assert _CHECK_COMMAND in runs[0].splitlines()
