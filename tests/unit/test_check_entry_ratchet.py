"""Entry ratchet check tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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
IPC_REGISTRY = "src/ante/ipc/registry.py"
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


IPC_SOURCE = """async def _h(svc, args, actor):
    return {}


def register_all_handlers(registry):
    registry.register("base.cmd", _h, is_mutating=True)
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tree(root: Path, files: dict[str, str] | None = None) -> Path:
    _write(root, MIDDLEWARE, HOOK_SOURCE)
    _write(root, REGISTRY, REGISTRY_SOURCE)
    _write(root, IPC_REGISTRY, IPC_SOURCE)
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
        "ipc_handlers_without_model": ["base.cmd"],
        "ipc_args_reads": {},
        "cli_direct_ipc_send": {},
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
        pytest.param(_without("cli_exits"), id="six-keys"),
        pytest.param(_without("ipc_args_reads"), id="six-keys-request"),
        pytest.param(_with(extra={}), id="eight-keys"),
        pytest.param(_with(cli_exits={"a.py": -1}), id="negative-count"),
        pytest.param(_with(cli_exits={"a.py": 1.5}), id="float-count"),
        pytest.param(_with(cli_exits={"a.py": True}), id="bool-count"),
        pytest.param(_with(cli_exits={"a.py": "1"}), id="string-count"),
        pytest.param(_with(cli_exits=[]), id="count-not-an-object"),
        pytest.param(_with(unregistered_codes=["B", "A"]), id="codes-unsorted"),
        pytest.param(_with(unregistered_codes=["A", "A"]), id="codes-duplicate"),
        pytest.param(_with(unregistered_codes=["A", 1]), id="codes-not-strings"),
        pytest.param(_with(unregistered_codes={"A": 1}), id="codes-not-a-list"),
        pytest.param(
            _with(ipc_handlers_without_model=["b", "a"]), id="commands-unsorted"
        ),
        pytest.param(
            _with(ipc_handlers_without_model="base.cmd"), id="commands-not-a-list"
        ),
        pytest.param(_with(ipc_args_reads={"a.b": -1}), id="reads-negative"),
        pytest.param(_with(cli_direct_ipc_send={"a.py": True}), id="sends-bool"),
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
        "ipc_handlers_without_model",
        "ipc_args_reads",
        "cli_direct_ipc_send",
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


SCRIPT = REPO_ROOT / "scripts" / "check_entry_ratchet.py"


def _script(
    args: list[str], cwd: Path, script: str | Path = SCRIPT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exits_0_when_tree_matches(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo", {COMMAND: ONE_OF_EACH})
    _freeze(root)
    result = _script(["--root", str(root)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""


def test_script_exits_1_when_tree_differs(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo", {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH + "    raise SystemExit(1)\n")
    result = _script(["--root", str(root)], tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout == ""


def test_script_exits_2_without_hook_function(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    _freeze(root)
    _write(root, MIDDLEWARE, "class AuthenticatedGroup:\n    pass\n")
    result = _script(["--root", str(root)], tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr


def test_script_default_root_is_its_checkout_from_any_cwd(tmp_path: Path) -> None:
    result = _script([], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("entry ratchet ok: ")


CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CI_STEP_NAME = "Entry ratchet check"
CI_RUN = "python scripts/check_entry_ratchet.py"


def _lint_step_runs(workflow: str, name: str) -> list[object]:
    data = yaml.safe_load(workflow)
    steps = data["jobs"]["lint"]["steps"]
    return [step.get("run") for step in steps if step.get("name") == name]


def test_ci_argv_and_cwd_pass_on_repository() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert _lint_step_runs(workflow, CI_STEP_NAME) == [CI_RUN]
    result = _script([], REPO_ROOT, script="scripts/check_entry_ratchet.py")
    assert result.returncode == 0, result.stdout + result.stderr


STEP_LINES = (
    "      - name: Entry ratchet check\n"
    "        run: python scripts/check_entry_ratchet.py\n"
)


@pytest.mark.parametrize(
    "altered",
    [
        pytest.param(
            STEP_LINES.replace("Entry ratchet check", "Entry ratchet"), id="renamed"
        ),
        pytest.param(
            STEP_LINES.replace(CI_RUN, "python scripts/check_comments.py"),
            id="other-run",
        ),
        pytest.param(STEP_LINES + "\n" + STEP_LINES, id="duplicated"),
    ],
)
def test_ci_step_assertion_rejects_altered_workflow(altered: str) -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count(STEP_LINES) == 1
    changed = workflow.replace(STEP_LINES, altered)
    assert _lint_step_runs(changed, CI_STEP_NAME) != [CI_RUN]


def test_registry_file_literals_outside_error_spec_are_in_code_set(
    tmp_path: Path,
) -> None:
    registry = REGISTRY_SOURCE + '_ALIAS = {"code": "ZZ_REG_DICT"}\n'
    root = _tree(tmp_path, {REGISTRY: registry})
    codes = checker.measure(root).unregistered_codes
    assert codes == {"HOOK_FALLBACK", "HOOK_ONLY", "ZZ_REG_DICT"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('x = {"status": "error", "code": "X"}', id="second-key"),
        pytest.param('x = {"ok": False, "message": "m", "code": "X"}', id="third-key"),
    ],
)
def test_code_key_after_other_dict_keys_is_counted(tmp_path: Path, source: str) -> None:
    assert _codes(tmp_path, source) == {"X"}


def test_registry_keywords_other_than_code_are_not_registered(
    tmp_path: Path,
) -> None:
    source = 'f(code="validation")\nf(code="not_found")\nf(code="REG")\n'
    assert _codes(tmp_path, source) == {"validation", "not_found"}


@pytest.mark.parametrize(
    "rel",
    [
        "src/ante/cli/__init__.py",
        "src/ante/cli/commands/__init__.py",
        "src/ante/cli/direct.py",
    ],
)
def test_init_and_direct_cli_files_are_counted(tmp_path: Path, rel: str) -> None:
    assert _counts(tmp_path, ONE_OF_EACH, rel=rel) == {key: 1 for key in COUNT_KEYS}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('obj.make(code="X")', id="1-method-call"),
        pytest.param('f()(code="X")', id="1-call-result"),
        pytest.param('x = [{"code": "X"}]', id="2-nested"),
        pytest.param('self.exc.ipc_error_code = "X"', id="4-attribute-chain"),
        pytest.param('excs[0].ipc_error_code = "X"', id="4-subscript"),
        pytest.param('f().ipc_error_code = "X"', id="4-call"),
        pytest.param('e.ipc_error_code: str = "X"', id="4-annassign"),
        pytest.param('class E(Exception):\n    ipc_error_code = "X"', id="4-class"),
        pytest.param(
            'class E(Exception):\n    ipc_error_code: str = "X"', id="4-class-annassign"
        ),
        pytest.param('getattr(self.e, "code", "X")', id="5-getattr-attribute"),
        pytest.param('getattr(a[0], "ipc_error_code", "X")', id="5-getattr-subscript"),
        pytest.param('getattr(f(), "code", "X")', id="5-getattr-call"),
        pytest.param('self.d.get("code", "X")', id="5-get-attribute"),
        pytest.param('resp["x"].get("code", "X")', id="5-get-subscript"),
        pytest.param('f().get("code", "X")', id="5-get-call"),
        pytest.param('fmts[0].error("m", "X")', id="6-subscript-receiver"),
        pytest.param('get_fmt().error("m", "X")', id="6-call-receiver"),
        pytest.param('get_logger().error("m", "X")', id="6-unnamed-logger-call"),
        pytest.param('x = self.e.code or "X"', id="7-attribute-chain"),
        pytest.param('x = f().code or "X"', id="7-call-code"),
        pytest.param('x = d["e"].ipc_error_code or "X"', id="7-subscript-ipc"),
        pytest.param('x = getattr(a[0], "code", "") or "X"', id="7-getattr-subscript"),
        pytest.param('x = f().get("code") or "X"', id="7-get-call"),
    ],
)
def test_position_with_non_name_receiver_is_counted(
    tmp_path: Path, source: str
) -> None:
    assert _codes(tmp_path, source) == {"X"}


@pytest.mark.parametrize(
    ("source", "key"),
    [
        ('fmts[0].error("m")', "cli_error_calls"),
        ('get_fmt().error("m")', "cli_error_calls"),
        ('self.a.b.error("m")', "cli_error_calls"),
        ('getattr(self.e, "ipc_error_code", "")', "ipc_error_code_reads"),
        ('getattr(a[0], "ipc_error_code", "")', "ipc_error_code_reads"),
        ('getattr(f(), "ipc_error_code", "")', "ipc_error_code_reads"),
    ],
)
def test_count_with_non_name_receiver_is_counted(
    tmp_path: Path, source: str, key: str
) -> None:
    counts = _counts(tmp_path, f"def g(self, a, f):\n    {source}\n")
    assert counts[key] == 1


def test_async_hook_function_is_excluded(tmp_path: Path) -> None:
    source = HOOK_SOURCE.replace("    def main(", "    async def main(")
    assert _counts(tmp_path, source, rel=MIDDLEWARE) == {key: 0 for key in COUNT_KEYS}


HEADER = "entry ratchet failed against scripts/entry_ratchet_baseline.json:"
ALTERNATIVE_LINES = [
    "새 에러 출구와 새 에러 코드 대신:",
    "  - 명령 안에서 끝내지 말고 타입 예외를 던진다",
    "  - 그 예외와 코드를 에러 레지스트리"
    "(src/ante/contracts/error_registry.py)에 등록한다",
]
MOVE_LINE = "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다."
LOWER_LINE = (
    "줄어든 값은 scripts/entry_ratchet_baseline.json의 기준선을 실측으로 낮춘다:"
)
CMD_PATH = "src/ante/cli/commands/demo.py"
OTHER_PATH = "src/ante/cli/commands/other.py"


def _run_split(root: Path, capsys: Capsys) -> tuple[int, str, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _assert_failure(
    root: Path, capsys: Capsys, expected: list[str], code: int = 1
) -> None:
    got, out, err = _run_split(root, capsys)
    assert (got, out) == (code, "")
    assert err.splitlines() == expected


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_full_output_when_count_grows(tmp_path: Path, capsys: Capsys, key: str) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH + COUNT_KEY_EDITS[key])
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"{key}\t{CMD_PATH}: actual 2, baseline 1 (+1)",
            *ALTERNATIVE_LINES,
            MOVE_LINE,
        ],
    )


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_full_output_when_count_drops_by_two(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    edit = COUNT_KEY_EDITS[key]
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH + edit + edit})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH)
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"{key}\t{CMD_PATH}: actual 1, baseline 3 (-2)",
            LOWER_LINE,
            f"  - {key}['{CMD_PATH}']를 1로 낮춘다",
        ],
    )


def test_full_output_for_new_file(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, OTHER, "import sys\n\n\ndef f():\n    sys.exit(1)\n")
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"cli_exits\t{OTHER_PATH}: actual 1, baseline 0 (+1)",
            *ALTERNATIVE_LINES,
            MOVE_LINE,
        ],
    )


def test_full_output_for_file_dropping_to_zero(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH})
    _freeze(root)
    _write(root, COMMAND, "def run():\n    return None\n")
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"cli_error_calls\t{CMD_PATH}: actual 0, baseline 1 (-1)",
            f"cli_exits\t{CMD_PATH}: actual 0, baseline 1 (-1)",
            f"ipc_error_code_reads\t{CMD_PATH}: actual 0, baseline 1 (-1)",
            LOWER_LINE,
            f"  - cli_error_calls에서 '{CMD_PATH}' 키를 지운다",
            f"  - cli_exits에서 '{CMD_PATH}' 키를 지운다",
            f"  - ipc_error_code_reads에서 '{CMD_PATH}' 키를 지운다",
        ],
    )


def test_full_output_for_added_code(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, CODE_SOURCE + '    fmt.error("m", code="NEW_B")\n')
    _assert_failure(
        root, capsys, [HEADER, "unregistered_codes\t+ NEW_B", *ALTERNATIVE_LINES]
    )


def test_full_output_for_removed_code(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, "def f(fmt):\n    return None\n")
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            "unregistered_codes\t- NEW_A",
            LOWER_LINE,
            "  - unregistered_codes에서 'NEW_A'를 지운다",
        ],
    )


def test_full_output_for_swapped_code(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path, {CORE: CODE_SOURCE})
    _freeze(root)
    _write(root, CORE, CODE_SOURCE.replace("NEW_A", "NEW_B"))
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            "unregistered_codes\t+ NEW_B",
            "unregistered_codes\t- NEW_A",
            *ALTERNATIVE_LINES,
            LOWER_LINE,
            "  - unregistered_codes에서 'NEW_A'를 지운다",
        ],
    )


def test_full_output_when_growth_and_drop_mix(tmp_path: Path, capsys: Capsys) -> None:
    two_exits = "import sys\n\n\ndef f():\n    sys.exit(1)\n    sys.exit(2)\n"
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH, OTHER: two_exits})
    _freeze(root)
    _write(root, COMMAND, ONE_OF_EACH + COUNT_KEY_EDITS["cli_error_calls"])
    _write(root, OTHER, "import sys\n\n\ndef f():\n    sys.exit(1)\n")
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"cli_error_calls\t{CMD_PATH}: actual 2, baseline 1 (+1)",
            f"cli_exits\t{OTHER_PATH}: actual 1, baseline 2 (-1)",
            *ALTERNATIVE_LINES,
            MOVE_LINE,
            LOWER_LINE,
            f"  - cli_exits['{OTHER_PATH}']를 1로 낮춘다",
        ],
    )


def test_full_output_when_passing_goes_to_stdout(
    tmp_path: Path, capsys: Capsys
) -> None:
    edit = COUNT_KEY_EDITS["cli_error_calls"]
    other = ONE_OF_EACH + edit * 3 + COUNT_KEY_EDITS["ipc_error_code_reads"]
    core = CODE_SOURCE + '    fmt.error("m", code="NEW_B")\n'
    root = _tree(tmp_path, {COMMAND: ONE_OF_EACH, OTHER: other, CORE: core})
    _freeze(root)
    code, out, err = _run_split(root, capsys)
    assert (code, err) == (0, "")
    assert out == (
        "entry ratchet ok: cli_error_calls 5, cli_exits 2, ipc_error_code_reads 3, "
        "unregistered_codes 4, ipc_handlers_without_model 1, ipc_args_reads 0, "
        "cli_direct_ipc_send 0 (baseline scripts/entry_ratchet_baseline.json)\n"
    )


def test_full_output_for_missing_baseline(tmp_path: Path, capsys: Capsys) -> None:
    _assert_failure(
        _tree(tmp_path),
        capsys,
        ["baseline file not found: scripts/entry_ratchet_baseline.json"],
        code=2,
    )


def test_full_output_for_missing_hook_function(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, MIDDLEWARE, "class AuthenticatedGroup:\n    pass\n")
    _assert_failure(
        root,
        capsys,
        [
            "hook function AuthenticatedGroup.main not found in "
            "src/ante/cli/middleware.py"
        ],
        code=2,
    )


def test_full_output_for_missing_hook_file(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    (root / MIDDLEWARE).unlink()
    _assert_failure(
        root,
        capsys,
        [
            "hook function AuthenticatedGroup.main not found: "
            "src/ante/cli/middleware.py is missing"
        ],
        code=2,
    )


def test_full_output_for_registry_failures(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, REGISTRY, "X = 1\n")
    _assert_failure(
        root,
        capsys,
        ["no ErrorSpec(code=...) found in src/ante/contracts/error_registry.py"],
        code=2,
    )
    (root / REGISTRY).unlink()
    _assert_failure(
        root,
        capsys,
        ["error registry not found: src/ante/contracts/error_registry.py"],
        code=2,
    )


def test_full_output_for_wrong_baseline_keys(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _write_baseline(root, _without("cli_exits"))
    _assert_failure(
        root,
        capsys,
        [
            "scripts/entry_ratchet_baseline.json must have exactly the keys "
            "['cli_direct_ipc_send', 'cli_error_calls', 'cli_exits', "
            "'ipc_args_reads', 'ipc_error_code_reads', "
            "'ipc_handlers_without_model', 'unregistered_codes'] "
            "(missing ['cli_exits'], extra [])"
        ],
        code=2,
    )


# ── 축 1: 요청 모델 키 ─────────────────────────────────────────────────────

CLI_IPC = "src/ante/cli/commands/ipc_demo.py"

IPC_HANDLERS = """async def _h(svc, args, actor):
    return {}


async def _reads(svc, args, actor):
    return args["k"]


async def _modeled(svc, request, actor):
    return {"k": request.k}
"""


def _ipc(*calls: str, handlers: str = IPC_HANDLERS) -> str:
    body = "".join(f"    {call}\n" for call in calls)
    return f"{handlers}\n\ndef register_all_handlers(registry):\n{body}"


REQUEST_BASE = _ipc(
    'registry.register("a.read", _reads, is_mutating=True)',
    'registry.register("a.model", _modeled, is_mutating=True, request_model=M)',
)
CLI_SEND = (
    "async def f(helpers):\n"
    '    await ipc_send("x", {})\n'
    '    await helpers.ipc_send("y", {})\n'
)

REQUEST_EDITS = {
    "ipc_handlers_without_model": _ipc(
        'registry.register("a.read", _reads, is_mutating=True)',
        'registry.register("a.model", _modeled, is_mutating=True, request_model=M)',
        'registry.register("a.new", _h, is_mutating=True)',
    ),
    "ipc_args_reads": _ipc(
        'registry.register("a.read", _reads, is_mutating=True)',
        'registry.register("a.model", _modeled, is_mutating=True, request_model=M)',
        handlers=IPC_HANDLERS.replace('return args["k"]', 'return args["k"], args'),
    ),
}


def _request_tree(root: Path, ipc: str = REQUEST_BASE) -> Path:
    return _tree(root, {IPC_REGISTRY: ipc, CLI_IPC: CLI_SEND})


def test_request_keys_measure_the_fixture(tmp_path: Path) -> None:
    data = _freeze(_request_tree(tmp_path))
    assert data["ipc_handlers_without_model"] == ["a.read"]
    assert data["ipc_args_reads"] == {"a.read": 1}
    assert data["cli_direct_ipc_send"] == {CLI_IPC: 2}


def test_request_keys_equal_to_baseline_pass(tmp_path: Path, capsys: Capsys) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    code, out = _run(root, capsys)
    assert code == 0, out


@pytest.mark.parametrize("key", sorted(REQUEST_EDITS))
def test_request_key_growth_fails(tmp_path: Path, capsys: Capsys, key: str) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_EDITS[key])
    code, out = _run(root, capsys)
    assert code == 1, out


def test_cli_direct_ipc_send_growth_fails(tmp_path: Path, capsys: Capsys) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, CLI_IPC, CLI_SEND + '    await ipc_send("z", {})\n')
    code, out = _run(root, capsys)
    assert code == 1, out


@pytest.mark.parametrize("key", sorted(REQUEST_EDITS))
def test_request_key_drop_without_lowering_fails(
    tmp_path: Path, capsys: Capsys, key: str
) -> None:
    root = _request_tree(tmp_path, REQUEST_EDITS[key])
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_BASE)
    code, out = _run(root, capsys)
    assert code == 1, out


def test_cli_direct_ipc_send_drop_without_lowering_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, CLI_IPC, 'async def f():\n    await ipc_send("x", {})\n')
    code, out = _run(root, capsys)
    assert code == 1, out


def test_swapped_command_with_same_set_size_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_BASE.replace('"a.read"', '"a.other"'))
    code, out = _run(root, capsys)
    assert code == 1, out


def _without_model(tmp_path: Path, call: str) -> frozenset[str]:
    root = _tree(tmp_path, {IPC_REGISTRY: _ipc(call)})
    without: frozenset[str] = checker.measure(root).ipc_handlers_without_model
    return without


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        pytest.param(
            'registry.register("a.b", _h, is_mutating=True)',
            frozenset({"a.b"}),
            id="no-keyword",
        ),
        pytest.param(
            'registry.register("a.b", _h, is_mutating=True, request_model=M)',
            frozenset(),
            id="model",
        ),
        pytest.param(
            'registry.register("a.b", _h, is_mutating=True, request_model=None)',
            frozenset({"a.b"}),
            id="model-none",
        ),
        pytest.param(
            'if True:\n        registry.register("a.b", _h, is_mutating=True)',
            frozenset({"a.b"}),
            id="nested-block",
        ),
    ],
)
def test_handlers_without_model_definition(
    tmp_path: Path, call: str, expected: frozenset[str]
) -> None:
    assert _without_model(tmp_path, call) == expected


def _reads_of(tmp_path: Path, handler: str, call: str | None = None) -> dict[str, int]:
    source = _ipc(
        call or 'registry.register("a.b", _x, is_mutating=True)', handlers=handler
    )
    reads: dict[str, int] = checker.measure(
        _tree(tmp_path, {IPC_REGISTRY: source})
    ).ipc_args_reads
    return reads


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        pytest.param('return args["k"]', {"a.b": 1}, id="subscript"),
        pytest.param('return args.get("k")', {"a.b": 1}, id="get"),
        pytest.param('return "k" in args', {"a.b": 1}, id="in"),
        pytest.param("return f(args)", {"a.b": 1}, id="argument"),
        pytest.param("return f(**args)", {"a.b": 1}, id="double-star"),
        pytest.param("a = args\n    return a['k'], a['j']", {"a.b": 1}, id="alias"),
        pytest.param("return {}", {}, id="zero-left-out"),
        pytest.param("args = {}\n    return 1", {}, id="store-only"),
        pytest.param(
            "def inner(svc, args):\n        return args\n    return inner",
            {"a.b": 1},
            id="nested-same-name",
        ),
    ],
)
def test_args_reads_definition(
    tmp_path: Path, statement: str, expected: dict[str, int]
) -> None:
    handler = f"async def _x(svc, args, actor):\n    {statement}\n"
    assert _reads_of(tmp_path, handler) == expected


def test_args_reads_follow_the_second_parameter_name(tmp_path: Path) -> None:
    handler = 'async def _x(svc, params, actor):\n    return params["k"], args\n'
    assert _reads_of(tmp_path, handler) == {"a.b": 1}


def test_args_reads_skip_commands_with_a_model(tmp_path: Path) -> None:
    handler = "async def _x(svc, request, actor):\n    return request.k\n"
    call = 'registry.register("a.b", _x, is_mutating=True, request_model=M)'
    assert _reads_of(tmp_path, handler, call) == {}


def test_args_reads_of_a_model_command_named_args_are_not_counted(
    tmp_path: Path,
) -> None:
    handler = 'async def _x(svc, args, actor):\n    return args["k"]\n'
    call = 'registry.register("a.b", _x, is_mutating=True, request_model=M)'
    assert _reads_of(tmp_path, handler, call) == {}


def _sends(tmp_path: Path, source: str, rel: str = CLI_IPC) -> dict[str, int]:
    sends: dict[str, int] = checker.measure(
        _tree(tmp_path, {rel: source})
    ).cli_direct_ipc_send
    return sends


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'async def f():\n    await ipc_send("x", {})\n', {CLI_IPC: 1}, id="name"
        ),
        pytest.param(
            'async def f(helpers):\n    await helpers.ipc_send("x", {})\n',
            {CLI_IPC: 1},
            id="attribute",
        ),
        pytest.param(
            "async def ipc_send(command, args):\n    return {}\n", {}, id="definition"
        ),
        pytest.param("x = ipc_send\n", {}, id="reference-not-call"),
        pytest.param(
            'async def f():\n    await ipc_sender("x", {})\n', {}, id="other-name"
        ),
    ],
)
def test_cli_direct_ipc_send_definition(
    tmp_path: Path, source: str, expected: dict[str, int]
) -> None:
    assert _sends(tmp_path, source) == expected


def test_cli_direct_ipc_send_only_covers_cli_files(tmp_path: Path) -> None:
    source = 'async def f():\n    await ipc_send("x", {})\n'
    assert _sends(tmp_path, source, rel=CORE) == {}


def test_cli_direct_ipc_send_counts_inside_the_hook(tmp_path: Path) -> None:
    source = HOOK_SOURCE + '        ipc_send("x", {})\n'
    assert _sends(tmp_path, source, rel=MIDDLEWARE) == {MIDDLEWARE: 1}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            "def other(registry):\n    pass\n",
            "register_all_handlers not found in src/ante/ipc/registry.py",
            id="no-function",
        ),
        pytest.param(
            "class X:\n    def register_all_handlers(self, registry):\n"
            '        registry.register("a.b", _h, is_mutating=True)\n',
            "register_all_handlers not found in src/ante/ipc/registry.py",
            id="method-not-top-level",
        ),
        pytest.param(
            _ipc("pass"),
            "no register(<command>, <handler>, ...) call in register_all_handlers "
            "of src/ante/ipc/registry.py",
            id="zero-registrations",
        ),
        pytest.param(
            _ipc("registry.register(NAME, _h, is_mutating=True)"),
            "no register(<command>, <handler>, ...) call in register_all_handlers "
            "of src/ante/ipc/registry.py",
            id="non-literal-name-only",
        ),
        pytest.param(
            _ipc('registry.register("a.b", lambda s, a, c: {}, is_mutating=True)'),
            "register('a.b') in src/ante/ipc/registry.py: the second positional "
            "argument is not the name of a top-level function",
            id="lambda",
        ),
        pytest.param(
            _ipc('registry.register("a.b", _missing, is_mutating=True)'),
            "register('a.b') in src/ante/ipc/registry.py: the second positional "
            "argument is not the name of a top-level function",
            id="unknown-name",
        ),
        pytest.param(
            _ipc('registry.register("a.b", handler=_h, is_mutating=True)'),
            "register('a.b') in src/ante/ipc/registry.py: the second positional "
            "argument is not the name of a top-level function",
            id="keyword-handler",
        ),
        pytest.param(
            _ipc(
                'registry.register("a.b", _one, is_mutating=True)',
                handlers="async def _one(svc):\n    return {}\n",
            ),
            "handler _one in src/ante/ipc/registry.py has fewer than two parameters",
            id="one-parameter",
        ),
    ],
)
def test_ipc_registry_failures_exit_2(
    tmp_path: Path, capsys: Capsys, source: str, message: str
) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    _write(root, IPC_REGISTRY, source)
    _assert_failure(root, capsys, [message], code=2)


def test_missing_ipc_registry_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    root = _tree(tmp_path)
    _freeze(root)
    (root / IPC_REGISTRY).unlink()
    _assert_failure(
        root,
        capsys,
        ["register_all_handlers not found: src/ante/ipc/registry.py is missing"],
        code=2,
    )


REQUEST_ALTERNATIVE_LINES = [
    "요청 모델 없는 IPC 명령과 인자 사전 읽기 대신:",
    "  - 요청 모델(src/ante/ipc/requests.py의 IPCRequest 하위 클래스)을 만들어 "
    "register(..., request_model=...)로 등록한다",
    "  - 핸들러는 사전 대신 그 모델의 필드를 읽는다",
]


def test_full_output_for_added_command(tmp_path: Path, capsys: Capsys) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_EDITS["ipc_handlers_without_model"])
    _assert_failure(
        root,
        capsys,
        [HEADER, "ipc_handlers_without_model\t+ a.new", *REQUEST_ALTERNATIVE_LINES],
    )


def test_full_output_for_command_given_a_model(tmp_path: Path, capsys: Capsys) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(
        root,
        IPC_REGISTRY,
        _ipc(
            'registry.register("a.read", _reads, is_mutating=True, request_model=M)',
            'registry.register("a.model", _modeled, is_mutating=True, request_model=M)',
        ),
    )
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            "ipc_handlers_without_model\t- a.read",
            "ipc_args_reads\ta.read: actual 0, baseline 1 (-1)",
            LOWER_LINE,
            "  - ipc_handlers_without_model에서 'a.read'를 지운다",
            "  - ipc_args_reads에서 'a.read' 키를 지운다",
        ],
    )


def test_full_output_when_args_reads_grow(tmp_path: Path, capsys: Capsys) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_EDITS["ipc_args_reads"])
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            "ipc_args_reads\ta.read: actual 2, baseline 1 (+1)",
            *REQUEST_ALTERNATIVE_LINES,
        ],
    )


def test_full_output_when_cli_direct_ipc_send_grows(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, CLI_IPC, CLI_SEND + '    await ipc_send("z", {})\n')
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"cli_direct_ipc_send\t{CLI_IPC}: actual 3, baseline 2 (+1)",
            MOVE_LINE,
        ],
    )


def test_full_output_when_cli_direct_ipc_send_drops(
    tmp_path: Path, capsys: Capsys
) -> None:
    root = _request_tree(tmp_path)
    _freeze(root)
    _write(root, CLI_IPC, 'async def f():\n    await ipc_send("x", {})\n')
    _assert_failure(
        root,
        capsys,
        [
            HEADER,
            f"cli_direct_ipc_send\t{CLI_IPC}: actual 1, baseline 2 (-1)",
            LOWER_LINE,
            f"  - cli_direct_ipc_send['{CLI_IPC}']를 1로 낮춘다",
        ],
    )


def test_script_exits_1_when_a_command_without_model_is_added(
    tmp_path: Path,
) -> None:
    root = _request_tree(tmp_path / "repo")
    _freeze(root)
    _write(root, IPC_REGISTRY, REQUEST_EDITS["ipc_handlers_without_model"])
    result = _script(["--root", str(root)], tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout == ""


def test_script_exits_2_when_a_handler_is_a_lambda(tmp_path: Path) -> None:
    root = _request_tree(tmp_path / "repo")
    _freeze(root)
    _write(
        root,
        IPC_REGISTRY,
        _ipc('registry.register("a.b", lambda s, a, c: {}, is_mutating=True)'),
    )
    result = _script(["--root", str(root)], tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr


def test_repository_request_keys_reach_the_end_state() -> None:
    measurement = checker.measure(REPO_ROOT)
    assert measurement.ipc_handlers_without_model == frozenset()
    assert measurement.ipc_args_reads == {}
    assert measurement.cli_direct_ipc_send


def test_an_empty_registry_is_an_error_not_an_empty_key(tmp_path: Path) -> None:
    root = _request_tree(tmp_path / "repo")
    _write(root, IPC_REGISTRY, _ipc("pass"))
    with pytest.raises(checker.CheckError) as info:
        checker.measure(root)
    assert str(info.value) == (
        "no register(<command>, <handler>, ...) call in "
        "register_all_handlers of src/ante/ipc/registry.py"
    )
