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
    return {key: measurement.counts(key).get(rel, 0) for key in checker.COUNT_KEYS}


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
    checker.CLI_ERROR_CALLS: '    fmt.error("again", code="REG")\n',
    checker.CLI_EXITS: "    sys.exit(2)\n",
    checker.IPC_ERROR_CODE_READS: '    getattr(e, "ipc_error_code", "")\n',
}


@pytest.mark.parametrize("key", checker.COUNT_KEYS)
def test_count_equal_to_baseline_passes(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    assert _freeze(root)[key] == {COMMAND: 1}
    code, out = _run(root, capsys)
    assert code == 0, out
    assert "entry ratchet ok" in out


@pytest.mark.parametrize("key", checker.COUNT_KEYS)
def test_count_increase_in_a_file_fails_with_alternatives(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH + COUNT_KEY_EDITS[key])
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{COMMAND}: actual 2, baseline 1 (+1)" in out
    assert "타입 예외를 던진다" in out
    assert "에러 레지스트리" in out


@pytest.mark.parametrize("key", checker.COUNT_KEYS)
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
    assert "타입 예외를 던진다" not in out


@pytest.mark.parametrize("key", checker.COUNT_KEYS)
def test_count_in_file_missing_from_baseline_fails(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, OTHER, "import sys\n\n\ndef f(ctx, fmt, e):\n" + COUNT_KEY_EDITS[key])
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{key}\t{OTHER}: actual 1, baseline 0 (+1)" in out
    assert checker.MOVE_HINT in out


@pytest.mark.parametrize("key", checker.COUNT_KEYS)
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
    data[checker.CLI_EXITS][COMMAND] = 0
    _write_baseline(root, data)
    code, out = _run(root, capsys)
    assert code == 1, out
    assert f"{checker.CLI_EXITS}에서 {COMMAND!r} 키를 지운다" in out


CODE_SOURCE = 'def f(fmt):\n    fmt.error("m", code="NEW_A")\n'


def test_same_code_set_passes(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    assert _freeze(root)[checker.UNREGISTERED_CODES] == [
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
    assert "에러 레지스트리" in out


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
    for key in checker.COUNT_KEYS:
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
    assert counts == {key: 1 for key in checker.COUNT_KEYS}


def test_other_method_of_the_hook_class_is_counted(tmp_path: Path) -> None:
    source = HOOK_SOURCE + '\n    def other(self, fmt):\n        fmt.error("m")\n'
    assert _counts(tmp_path, source, rel=MIDDLEWARE)[checker.CLI_ERROR_CALLS] == 1


def test_main_of_another_class_is_counted(tmp_path: Path) -> None:
    source = (
        HOOK_SOURCE
        + '\n\nclass Other:\n    def main(self, fmt):\n        fmt.error("m")\n'
    )
    assert _counts(tmp_path, source, rel=MIDDLEWARE)[checker.CLI_ERROR_CALLS] == 1


def test_hook_with_same_name_in_another_file_is_counted(tmp_path: Path) -> None:
    counts = _counts(tmp_path, HOOK_SOURCE)
    assert counts == {key: 1 for key in checker.COUNT_KEYS}


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
    assert _counts(tmp_path, source)[checker.CLI_EXITS] == 1


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
    assert _counts(tmp_path, source)[checker.CLI_EXITS] == 0


def test_sys_alias_is_per_file(tmp_path: Path) -> None:
    _tree(tmp_path, {OTHER: "import sys as s\n"})
    source = "def f(s):\n    s.exit(1)\n"
    assert _counts(tmp_path, source)[checker.CLI_EXITS] == 0


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
    assert counts[checker.CLI_ERROR_CALLS] == expected


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
    assert counts[checker.IPC_ERROR_CODE_READS] == expected


def test_count_keys_only_cover_cli_files(tmp_path: Path) -> None:
    measurement = checker.measure(_tree(tmp_path, {CORE: ONE_OF_EACH}))
    for key in checker.COUNT_KEYS:
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
    for key in checker.COUNT_KEYS:
        assert measurement.counts(key) == {COMMAND: 1}


def test_baseline_json_round_trips_through_parse(tmp_path: Path) -> None:
    measurement = checker.measure(_tree(tmp_path, {COMMAND: ONE_OF_EACH}))
    assert checker.parse_baseline(checker.baseline_json(measurement)) == measurement


def _valid_baseline() -> dict[str, Any]:
    return {
        checker.CLI_ERROR_CALLS: {},
        checker.CLI_EXITS: {},
        checker.IPC_ERROR_CODE_READS: {},
        checker.UNREGISTERED_CODES: ["A", "B"],
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
        pytest.param(_without(checker.CLI_EXITS), id="three-keys"),
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
