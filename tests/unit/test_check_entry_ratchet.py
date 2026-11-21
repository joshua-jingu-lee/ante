"""Entry ratchet check tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_entry_ratchet.py"
    spec = importlib.util.spec_from_file_location("check_entry_ratchet", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load entry ratchet check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

Capsys = pytest.CaptureFixture[str]

MIDDLEWARE = "src/ante/cli/middleware.py"
REGISTRY = "src/ante/contracts/error_registry.py"
COMMAND = "src/ante/cli/commands/demo.py"
OTHER = "src/ante/cli/commands/other.py"
CORE = "src/ante/core/demo.py"

COUNT_KEYS = ("cli_error_calls", "cli_exits", "ipc_error_code_reads")
MOVE_HINT = "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다."
REGISTER_HINT = (
    "그 예외와 코드를 에러 레지스트리(src/ante/contracts/error_registry.py)에 등록한다"
)
THROW_HINT = "타입 예외를 던진다"

HOOK_SOURCE = """import sys as _sys


class AuthenticatedGroup:
    def main(self, ctx, fmt, e):
        fmt.error("m", code="HOOK_ONLY")
        code = getattr(e, "ipc_error_code", "") or "HOOK_FALLBACK"
        _sys.exit(1)
"""

REGISTRY_SOURCE = """class ErrorSpec:
    pass


A = ErrorSpec(code="REG", category="validation")
B = ErrorSpec(code="REG_TWO", category="not_found")
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tree(root: Path, files: dict[str, str] | None = None) -> Path:
    _write(root, MIDDLEWARE, HOOK_SOURCE)
    _write(root, REGISTRY, REGISTRY_SOURCE)
    for rel, text in (files or {}).items():
        _write(root, rel, text)
    return root


def _write_baseline(root: Path, data: object) -> None:
    path = root / "scripts" / "entry_ratchet_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )


def _freeze(root: Path) -> dict[str, Any]:
    text = checker.baseline_json(checker.measure(root))
    _write_baseline(root, text)
    data: dict[str, Any] = json.loads(text)
    return data


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _counts(tmp_path: Path, source: str, rel: str = COMMAND) -> dict[str, int]:
    measurement = checker.measure(_tree(tmp_path, {rel: source}))
    return {key: measurement.counts(key).get(rel, 0) for key in COUNT_KEYS}


def _codes(tmp_path: Path, source: str) -> frozenset[str]:
    codes: frozenset[str] = checker.measure(
        _tree(tmp_path, {CORE: source})
    ).unregistered_codes
    return codes - {"HOOK_FALLBACK", "HOOK_ONLY"}


ONE_OF_EACH = """import sys


def run(ctx, fmt, e):
    fmt.error("m", code="REG")
    getattr(e, "ipc_error_code", "")
    raise SystemExit(1)
"""

COUNT_KEY_EDITS = {
    "cli_error_calls": '    fmt.error("again", code="REG")\n',
    "cli_exits": "    sys.exit(2)\n",
    "ipc_error_code_reads": '    getattr(e, "ipc_error_code", "")\n',
}


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_count_equal_to_baseline_passes(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    assert _freeze(root)[key] == {COMMAND: 1}
    code, out = _run(root, capsys)
    assert code == 0, out
    assert "entry ratchet ok" in out


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_count_increase_in_a_file_fails_with_alternatives(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH + COUNT_KEY_EDITS[key])
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{COMMAND}: actual 2, baseline 1 (+1)" in out
    assert THROW_HINT in out
    assert REGISTER_HINT in out


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_count_decrease_without_lowering_baseline_fails(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH + COUNT_KEY_EDITS[key]})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH)
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{COMMAND}: actual 1, baseline 2 (-1)" in out
    assert f"{key}[{COMMAND!r}]를 1로 낮춘다" in out
    assert MOVE_HINT not in out
    assert THROW_HINT not in out
    assert REGISTER_HINT not in out


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_count_in_file_missing_from_baseline_fails(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, OTHER, "import sys\n\n\ndef f(ctx, fmt, e):\n" + COUNT_KEY_EDITS[key])
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{OTHER}: actual 1, baseline 0 (+1)" in out
    assert MOVE_HINT in out


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_file_dropping_to_zero_with_key_left_in_baseline_fails(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, "def run():\n    return None\n")
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{COMMAND}: actual 0, baseline 1 (-1)" in out
    assert f"{key}에서 {COMMAND!r} 키를 지운다" in out


def test_zero_count_left_in_baseline_fails(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    data = _freeze(root)
    data["cli_exits"][COMMAND] = 0
    _write_baseline(root, data)
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"cli_exits에서 {COMMAND!r} 키를 지운다" in out


CODE_SOURCE = 'def f(fmt):\n    fmt.error("m", code="NEW_A")\n'


def test_same_code_set_passes(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    assert _freeze(root)["unregistered_codes"] == [
        "HOOK_FALLBACK",
        "HOOK_ONLY",
        "NEW_A",
    ]
    code, out = _run(root, capsys)
    assert code == 0, out
    assert "unregistered_codes 3" in out


def test_added_code_fails_with_alternatives(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, CODE_SOURCE + '    fmt.error("m", code="NEW_B")\n')
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "unregistered_codes\t+ NEW_B" in out
    assert REGISTER_HINT in out
    assert THROW_HINT in out


def test_removed_code_without_lowering_baseline_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, "def f(fmt):\n    return None\n")
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "unregistered_codes\t- NEW_A" in out
    assert "unregistered_codes에서 'NEW_A'를 지운다" in out
    assert REGISTER_HINT not in out


def test_swapped_code_with_same_set_size_fails(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, CODE_SOURCE.replace("NEW_A", "NEW_B"))
    code, out = _run(root, capsys)
    assert code == 1, out
    assert "unregistered_codes\t+ NEW_B" in out
    assert "unregistered_codes\t- NEW_A" in out


def test_hook_body_is_not_counted(tmp_path: Path) -> None:
    measurement = checker.measure(_tree(tmp_path))
    for key in COUNT_KEYS:
        assert MIDDLEWARE not in measurement.counts(key)


def test_same_calls_in_another_function_of_the_hook_file_are_counted(
    tmp_path: Path,
) -> None:
    outside = (
        "\n\ndef helper(ctx, fmt, e):\n"
        '    fmt.error("m", code="REG")\n'
        "    _sys.exit(1)\n"
        '    getattr(e, "ipc_error_code", "")\n'
    )
    counts = _counts(tmp_path, HOOK_SOURCE + outside, rel=MIDDLEWARE)
    assert counts == {key: 1 for key in COUNT_KEYS}


def test_other_method_of_the_hook_class_is_counted(tmp_path: Path) -> None:
    source = HOOK_SOURCE + '\n    def other(self, fmt):\n        fmt.error("m")\n'
    assert _counts(tmp_path, source, rel=MIDDLEWARE)["cli_error_calls"] == 1


def test_main_of_another_class_is_counted(tmp_path: Path) -> None:
    source = (
        HOOK_SOURCE
        + '\n\nclass Other:\n    def main(self, fmt):\n        fmt.error("m")\n'
    )
    assert _counts(tmp_path, source, rel=MIDDLEWARE)["cli_error_calls"] == 1


def test_hook_with_same_name_in_another_file_is_counted(tmp_path: Path) -> None:
    counts = _counts(tmp_path, HOOK_SOURCE)
    assert counts == {key: 1 for key in COUNT_KEYS}


def test_unregistered_literal_inside_hook_is_in_code_set(tmp_path: Path) -> None:
    codes = checker.measure(_tree(tmp_path)).unregistered_codes
    assert codes == {"HOOK_ONLY", "HOOK_FALLBACK"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("class AuthenticatedGroup:\n    pass\n", id="no-main"),
        pytest.param(
            "class Other:\n    def main(self):\n        pass\n", id="other-class"
        ),
        pytest.param(
            "def outer():\n    class AuthenticatedGroup:\n"
            "        def main(self):\n            pass\n",
            id="nested-class",
        ),
    ],
)
def test_tree_without_hook_function_exits_2(
    tmp_path: Path, capsys: Capsys, source: str
) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, MIDDLEWARE, source)
    code, out = _run(root, capsys)
    assert code == 2, out
    assert "AuthenticatedGroup.main" in out


def test_missing_hook_file_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    (root / MIDDLEWARE).unlink()
    code, out = _run(root, capsys)
    assert code == 2, out
    assert "AuthenticatedGroup.main" in out


def test_missing_or_empty_registry_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, REGISTRY, "X = 1\n")
    code, out = _run(root, capsys)
    assert code == 2, out
    (root / REGISTRY).unlink()
    code, out = _run(root, capsys)
    assert code == 2, out
    assert REGISTRY in out


@pytest.mark.parametrize(
    "statement",
    [
        "raise SystemExit",
        "raise SystemExit(1)",
        "raise click.exceptions.Exit(1)",
        "raise Exit(1)",
        "ctx.exit(1)",
        "sys.exit(1)",
        "s.exit(1)",
    ],
)
def test_each_exit_form_counts_once(tmp_path: Path, statement: str) -> None:
    source = f"import sys\nimport sys as s\n\n\ndef f(ctx):\n    {statement}\n"
    assert _counts(tmp_path, source)["cli_exits"] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "other.exit(1)",
        "self.ctx.exit(1)",
        "os.exit(1)",
        "raise RuntimeError(1)",
        "raise",
    ],
)
def test_exit_on_other_receiver_or_raise_of_other_name_is_not_counted(
    tmp_path: Path, statement: str
) -> None:
    source = f"import os\nimport sys\n\n\ndef f(other):\n    {statement}\n"
    assert _counts(tmp_path, source)["cli_exits"] == 0


def test_sys_alias_is_per_file(tmp_path: Path) -> None:
    _tree(tmp_path, {OTHER: "import sys as s\n"})
    source = "def f(s):\n    s.exit(1)\n"
    assert _counts(tmp_path, source)["cli_exits"] == 0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('fmt.error("m")', 1),
        ('self._fmt.error("m", code="X")', 1),
        ('logger.error("m")', 1),
        ('fmt.errors("m")', 0),
        ('error("m")', 0),
    ],
)
def test_error_calls_match_attribute_name_exactly(
    tmp_path: Path, source: str, expected: int
) -> None:
    counts = _counts(tmp_path, f"def f(fmt, self, logger, error):\n    {source}\n")
    assert counts["cli_error_calls"] == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('getattr(e, "ipc_error_code", "")', 1),
        ('getattr(e, "ipc_error_code")', 1),
        ('getattr(e, "code", "")', 0),
        ("e.ipc_error_code", 0),
        ('getattr(e, name, "")', 0),
    ],
)
def test_ipc_error_code_reads_match_getattr_literal(
    tmp_path: Path, source: str, expected: int
) -> None:
    counts = _counts(tmp_path, f"def f(e, name):\n    {source}\n")
    assert counts["ipc_error_code_reads"] == expected


def test_count_keys_only_cover_cli_files(tmp_path: Path) -> None:
    measurement = checker.measure(_tree(tmp_path, {CORE: ONE_OF_EACH}))
    for key in COUNT_KEYS:
        assert CORE not in measurement.counts(key)


POSITIONS = [
    pytest.param('f(code="{c}")', id="1-keyword"),
    pytest.param('x = {{"code": "{c}"}}', id="2-dict"),
    pytest.param('class E(Exception):\n    code = "{c}"', id="3-class-assign"),
    pytest.param('class E(Exception):\n    code: str = "{c}"', id="3-class-annassign"),
    pytest.param('e.ipc_error_code = "{c}"', id="4-attribute"),
    pytest.param('getattr(e, "ipc_error_code", "{c}")', id="5-getattr-ipc"),
    pytest.param('getattr(e, "code", "{c}")', id="5-getattr-code"),
    pytest.param('d.get("code", "{c}")', id="5-get"),
    pytest.param('fmt.error("m", "{c}")', id="6-error-positional"),
    pytest.param('_emit_auth_error(ctx, "{c}", "m")', id="6-emit-auth-error"),
    pytest.param('getattr(e, "ipc_error_code", "") or "{c}"', id="7-or-read"),
    pytest.param('f(code=c or "{c}")', id="7-or-in-position"),
]


@pytest.mark.parametrize("template", POSITIONS)
def test_unregistered_literal_in_position_is_in_code_set(
    tmp_path: Path, template: str
) -> None:
    assert _codes(tmp_path, template.format(c="NOT_REGISTERED")) == {"NOT_REGISTERED"}


@pytest.mark.parametrize("template", POSITIONS)
def test_registered_literal_in_position_is_not_in_code_set(
    tmp_path: Path, template: str
) -> None:
    assert _codes(tmp_path, template.format(c="REG")) == frozenset()


@pytest.mark.parametrize("template", POSITIONS)
def test_empty_string_in_position_is_not_in_code_set(
    tmp_path: Path, template: str
) -> None:
    assert _codes(tmp_path, template.format(c="")) == frozenset()


@pytest.mark.parametrize(
    "source",
    [
        'logger.error("m", "X")',
        'self._logger.error("m", "X")',
        'log.error("m", "X")',
        'fmt.error("m")',
        'f("X", "Y")',
        'x = "X" or y',
        'code = "X"',
        'd["code"] = "X"',
        'getattr(e, "message", "X")',
        'd.get("message", "X")',
        'f(kind="X")',
    ],
)
def test_literal_outside_positions_is_not_in_code_set(
    tmp_path: Path, source: str
) -> None:
    assert _codes(tmp_path, source) == frozenset()


def test_known_limits_are_not_counted(tmp_path: Path) -> None:
    source = (
        'code = "VIA_VARIABLE"\n'
        "f(code=code)\n"
        '_helper(fmt, "VIA_HELPER")\n'
        'f(code="A" if x else "B")\n'
        'f(code=f"F_{x}")\n'
    )
    assert _codes(tmp_path, source) == frozenset()


def test_code_set_covers_files_outside_cli(tmp_path: Path) -> None:
    assert _codes(tmp_path, 'f(code="CORE_CODE")') == {"CORE_CODE"}


def test_registered_codes_come_from_error_spec_code_keyword(tmp_path: Path) -> None:
    registry = (
        REGISTRY_SOURCE + 'C = ErrorSpec(category="x")\nD = Other(code="OTHER")\n'
    )
    root = _tree(tmp_path, {REGISTRY: registry, CORE: 'f(code="OTHER")'})
    assert "OTHER" in checker.measure(root).unregistered_codes


def test_measure_uses_posix_paths_and_skips_zero_files(tmp_path: Path) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH, OTHER: "x = 1\n"})
    measurement = checker.measure(root)
    for key in COUNT_KEYS:
        assert measurement.counts(key) == {COMMAND: 1}


def test_baseline_json_round_trips_through_parse(tmp_path: Path) -> None:
    measurement = checker.measure(_tree(tmp_path, {COMMAND: ONE_OF_EACH}))
    assert checker.parse_baseline(checker.baseline_json(measurement)) == measurement


def _valid_baseline() -> dict[str, Any]:
    return {
        "cli_error_calls": {},
        "cli_exits": {},
        "ipc_error_code_reads": {},
        "unregistered_codes": ["A", "B"],
    }


def _with(**changes: object) -> dict[str, Any]:
    data = _valid_baseline()
    data.update(changes)
    return data


def _without(key: str) -> dict[str, Any]:
    data = _valid_baseline()
    del data[key]
    return data


@pytest.mark.parametrize(
    "baseline",
    [
        pytest.param("{not json", id="not-json"),
        pytest.param([], id="not-an-object"),
        pytest.param(_without("cli_exits"), id="three-keys"),
        pytest.param(_with(extra={}), id="five-keys"),
        pytest.param(_with(cli_exits={"a.py": -1}), id="negative-count"),
        pytest.param(_with(cli_exits={"a.py": 1.5}), id="float-count"),
        pytest.param(_with(cli_exits={"a.py": True}), id="bool-count"),
        pytest.param(_with(cli_exits={"a.py": "1"}), id="string-count"),
        pytest.param(_with(cli_exits=[]), id="count-not-an-object"),
        pytest.param(_with(unregistered_codes=["B", "A"]), id="codes-unsorted"),
        pytest.param(_with(unregistered_codes=["A", "A"]), id="codes-duplicate"),
        pytest.param(_with(unregistered_codes=["A", 1]), id="codes-not-strings"),
        pytest.param(_with(unregistered_codes={"A": 1}), id="codes-not-a-list"),
    ],
)
def test_malformed_baseline_exits_2(
    tmp_path: Path, capsys: Capsys, baseline: object
) -> None:
    root = _tree(tmp_path)
    _write_baseline(root, baseline)
    code, out = _run(root, capsys)
    assert code == 2, out
    assert "entry_ratchet_baseline.json" in out


def test_missing_baseline_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    code, out = _run(_tree(tmp_path), capsys)
    assert code == 2, out
    assert "baseline file not found" in out


def test_unparsable_source_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, CORE, "def broken(:\n")
    code, out = _run(root, capsys)
    assert code == 2, out
    assert CORE in out


def test_unexpected_exception_exits_2(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(tmp_path)
    _freeze(root)

    def boom(_root: Path) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(checker, "measure", boom)
    code, out = _run(root, capsys)
    assert code == 2, out
    assert "ValueError: boom" in out


def test_repository_baseline_matches_measurement() -> None:
    assert checker.read_baseline(REPO_ROOT) == checker.measure(REPO_ROOT)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "class AuthenticatedGroup:\n    def main2(self):\n        pass\n",
            id="function-renamed",
        ),
        pytest.param(
            "class AuthenticatedGroupX:\n    def main(self):\n        pass\n",
            id="class-renamed",
        ),
        pytest.param("def main():\n    pass\n", id="module-function"),
    ],
)
def test_renamed_hook_exits_2(tmp_path: Path, capsys: Capsys, source: str) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, MIDDLEWARE, source)
    code, out = _run(root, capsys)
    assert code == 2, out
    assert "AuthenticatedGroup.main" in out


def test_hook_in_another_file_does_not_stand_in_for_middleware(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _tree(tmp_path, {COMMAND: HOOK_SOURCE})
    _freeze(root)
    (root / MIDDLEWARE).unlink()
    code, out = _run(root, capsys)
    assert code == 2, out


@pytest.mark.parametrize(
    "statement",
    [
        "raise Exit",
        "raise exceptions.Exit()",
        "raise SystemExit(1) from e",
        "ctx.exit()",
    ],
)
def test_more_exit_forms_count_once(tmp_path: Path, statement: str) -> None:
    source = f"import sys\n\n\ndef f(ctx, e):\n    {statement}\n"
    assert _counts(tmp_path, source)["cli_exits"] == 1


def test_alias_of_another_module_is_not_sys(tmp_path: Path) -> None:
    source = (
        "import os as s\nimport sysconfig as t\n\n\n"
        "def f():\n    s.exit(1)\n    t.exit(1)\n"
    )
    assert _counts(tmp_path, source)["cli_exits"] == 0


def test_sys_alias_imported_inside_a_function_counts(tmp_path: Path) -> None:
    source = "def f():\n    import sys as _s\n\n    _s.exit(1)\n"
    assert _counts(tmp_path, source)["cli_exits"] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "context.exit(1)",
        "ctxs.exit(1)",
        "ctx.exits(1)",
        "sys.exits(1)",
        "exit(1)",
        "x = SystemExit",
        "SystemExit(1)",
        "x = ctx.exit",
        "raise SystemExitError(1)",
        "raise MyExit(1)",
        "raise ValueError from SystemExit",
        "try:\n        pass\n    except SystemExit:\n        pass",
    ],
)
def test_near_miss_exit_forms_are_not_counted(tmp_path: Path, statement: str) -> None:
    source = f"import sys\n\n\ndef f(ctx, context, ctxs):\n    {statement}\n"
    assert _counts(tmp_path, source)["cli_exits"] == 0


@pytest.mark.parametrize(
    "source",
    [
        "x = fmt.error",
        'fmt.Error("m")',
        'fmt.error_("m")',
        'fmt.raise_error("m")',
    ],
)
def test_near_miss_error_calls_are_not_counted(tmp_path: Path, source: str) -> None:
    counts = _counts(tmp_path, f"def f(fmt):\n    {source}\n")
    assert counts["cli_error_calls"] == 0


@pytest.mark.parametrize(
    "source",
    [
        'getattr(e, "ipc_error_codes", "")',
        'getattr(e, "ipc_error_cod", "")',
        'x.getattr(e, "ipc_error_code", "")',
        'hasattr(e, "ipc_error_code")',
        'getattr("ipc_error_code", e, "")',
    ],
)
def test_near_miss_ipc_error_code_reads_are_not_counted(
    tmp_path: Path, source: str
) -> None:
    counts = _counts(tmp_path, f"def f(e, x):\n    {source}\n")
    assert counts["ipc_error_code_reads"] == 0


@pytest.mark.parametrize(
    "rel",
    ["src/ante/cli_tools.py", "src/ante/client/demo.py", "src/cli/demo.py"],
)
def test_count_keys_skip_paths_outside_cli_directory(tmp_path: Path, rel: str) -> None:
    measurement = checker.measure(_tree(tmp_path, {rel: ONE_OF_EACH}))
    for key in COUNT_KEYS:
        assert measurement.counts(key) == {}


def test_count_keys_cover_nested_cli_directories(tmp_path: Path) -> None:
    rel = "src/ante/cli/commands/sub/deep.py"
    assert _counts(tmp_path, ONE_OF_EACH, rel=rel) == {key: 1 for key in COUNT_KEYS}


@pytest.mark.parametrize(
    "rel", ["src/other/demo.py", "scripts/demo.py", "tests/demo.py"]
)
def test_code_set_skips_files_outside_src_ante(tmp_path: Path, rel: str) -> None:
    root = _tree(tmp_path, {rel: 'f(code="OUTSIDE")'})
    assert "OUTSIDE" not in checker.measure(root).unregistered_codes


def test_error_spec_outside_registry_does_not_register(tmp_path: Path) -> None:
    assert _codes(tmp_path, 'ErrorSpec(code="ELSEWHERE")') == {"ELSEWHERE"}


def test_error_spec_with_attribute_name_registers(tmp_path: Path) -> None:
    registry = REGISTRY_SOURCE + 'C = registry.ErrorSpec(code="VIA_ATTR")\n'
    root = _tree(tmp_path, {REGISTRY: registry, CORE: 'f(code="VIA_ATTR")'})
    assert "VIA_ATTR" not in checker.measure(root).unregistered_codes


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('x = {"code": c or "X"}', id="2-dict"),
        pytest.param('class E(Exception):\n    code = c or "X"', id="3-class"),
        pytest.param('e.ipc_error_code = c or "X"', id="4-attribute"),
        pytest.param('fmt.error("m", c or "X")', id="6-error-positional"),
        pytest.param('_emit_auth_error(c, d or "X")', id="6-emit-or"),
        pytest.param('x = e.code or "X"', id="7-attr-code"),
        pytest.param('x = e.ipc_error_code or "X"', id="7-attr-ipc"),
        pytest.param('x = d.get("code") or "X"', id="7-get-code"),
        pytest.param('x = getattr(e, "code", "") or "X"', id="7-getattr-code"),
        pytest.param('x = "X" or getattr(e, "code", "")', id="7-literal-first"),
        pytest.param('catalog.error("m", "X")', id="6-catalog"),
        pytest.param('blog.error("m", "X")', id="6-blog"),
        pytest.param('xlogger.error("m", "X")', id="6-xlogger"),
        pytest.param('lo.error("m", "X")', id="6-lo"),
        pytest.param('loc.error("m", "X")', id="6-loc"),
        pytest.param('self.fmt.error("m", "X")', id="6-attribute-receiver"),
        pytest.param('fmt.error(m, "X")', id="6-name-first"),
        pytest.param('_emit_auth_error(c, "X")', id="6-emit-two-args"),
        pytest.param('f(code="X", kind="Y")', id="1-only-code-keyword"),
    ],
)
def test_near_position_literal_that_is_counted(tmp_path: Path, source: str) -> None:
    assert _codes(tmp_path, source) == {"X"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('f(codes="X")', id="1-keyword-name"),
        pytest.param('f(error_code="X")', id="1-keyword-suffix"),
        pytest.param('f(**{"kind": "X"})', id="1-double-star"),
        pytest.param('x = {"codes": "X"}', id="2-key-name"),
        pytest.param('x = {code: "X"}', id="2-name-key"),
        pytest.param('class E(Exception):\n    codes = "X"', id="3-name"),
        pytest.param(
            'class E(Exception):\n    def f(self):\n        code = "X"',
            id="3-not-body",
        ),
        pytest.param('class E(Exception):\n    x.code = "X"', id="3-attribute-target"),
        pytest.param('self.code = "X"', id="4-code-attribute"),
        pytest.param('e.ipc_error_codes = "X"', id="4-attribute-name"),
        pytest.param('ipc_error_code = "X"', id="4-module-name"),
        pytest.param('getattr(e, "codes", "X")', id="5-getattr-codes"),
        pytest.param('getattr(e, "error_code", "X")', id="5-getattr-suffix"),
        pytest.param('getattr(e, "ipc_error_codes", "X")', id="5-getattr-ipc-name"),
        pytest.param('x.getattr(e, "code", "X")', id="5-method-getattr"),
        pytest.param('d.get("codes", "X")', id="5-get-name"),
        pytest.param('d.pop("code", "X")', id="5-pop"),
        pytest.param('d.get(k, "X")', id="5-get-variable"),
        pytest.param('fmt.error("X")', id="6-first-positional"),
        pytest.param('fmt.error(m, a, "X")', id="6-third-positional"),
        pytest.param('fmt.errors("m", "X")', id="6-errors"),
        pytest.param('fmt.error("m", code=c, extra="X")', id="6-keyword-only"),
        pytest.param('logx.error("m", "X")', id="6-logx"),
        pytest.param('_log.error("m", "X")', id="6-underscore-log"),
        pytest.param('__logger.error("m", "X")', id="6-dunder-logger"),
        pytest.param('self.log.error("m", "X")', id="6-self-log"),
        pytest.param('_emit_auth_errors(c, "X", "m")', id="6-emit-name"),
        pytest.param('_emit_auth_error(c, m, "X")', id="6-emit-third"),
        pytest.param('emit_auth_error(c, "X", "m")', id="6-emit-public"),
        pytest.param('f(code=c and "X")', id="7-and"),
        pytest.param('f(kind=c or "X")', id="7-or-outside-position"),
        pytest.param('x = e.codes or "X"', id="7-attr-codes"),
        pytest.param('x = getattr(e, "message", "") or "X"', id="7-getattr-message"),
        pytest.param('x = d.get("message") or "X"', id="7-get-message"),
        pytest.param('x = (e.code or y) + "X"', id="7-not-operand"),
    ],
)
def test_near_position_literal_that_is_not_counted(tmp_path: Path, source: str) -> None:
    assert _codes(tmp_path, source) == frozenset()


def test_empty_code_list_is_valid(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _write(
        root,
        MIDDLEWARE,
        "class AuthenticatedGroup:\n    def main(self):\n        pass\n",
    )
    _write_baseline(root, {**_valid_baseline(), "unregistered_codes": []})
    code, out = _run(root, capsys)
    assert code == 0, out


def test_baseline_file_has_exactly_the_contract_keys(tmp_path: Path) -> None:
    data = _freeze(_tree(tmp_path))
    assert set(data) == {
        "cli_error_calls",
        "cli_exits",
        "ipc_error_code_reads",
        "unregistered_codes",
    }


def test_baseline_is_read_from_the_contract_path(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _tree(tmp_path)
    data = _freeze(root)
    baseline = root / "scripts" / "entry_ratchet_baseline.json"
    baseline.rename(root / "scripts" / "other_baseline.json")
    code, _ = _run(root, capsys)
    assert code == 2
    _write_baseline(root, data)
    code, out = _run(root, capsys)
    assert code == 0, out
