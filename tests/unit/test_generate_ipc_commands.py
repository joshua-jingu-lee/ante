"""``scripts/generate_ipc_commands.py``의 표기·결정성·``--check`` 테스트.

요청 필드의 타입 표기는 가지마다 등록하지 않는 픽스처 모델의 리터럴로 잠근다.
생성 문서가 레지스트리와 어긋나는지는 ``--check`` 하나가 판정한다.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ante.contracts.cli_registry import all_contracts
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.requests import AccountId, IPCRequest, IsoDate

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _ROOT / "scripts" / "generate_ipc_commands.py"
_SPEC = importlib.util.spec_from_file_location("generate_ipc_commands", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


class _Leaf(IPCRequest):
    flag: bool | None = None


def _unknown(value: str) -> str:
    return value


class _Branches(IPCRequest):
    plain: str
    number: int = 60
    ratio: float = 1.5
    enabled: bool = True
    account: AccountId
    maybe_account: AccountId | None = None
    day: IsoDate | None = None
    secret: SecretStr
    tags: list[str] = []
    free: dict[str, Any] = {}
    maybe_free: dict[str, Any] | None = None
    status: Literal["registered", "adopted"]
    maybe_text: str | None = None
    leaf: _Leaf = Field(default_factory=_Leaf)
    label: str = "IPC halt"
    empty: str = ""
    positive: float | None = Field(default=None, gt=0)
    bounded: int = Field(default=1, ge=0, le=10)
    below: float = Field(default=0.5, lt=1.5)
    count: int = Field(gt=0)


class _SecretWithDefault(IPCRequest):
    token: SecretStr = SecretStr("hidden-value")


class _UnknownValidator(IPCRequest):
    value: Annotated[str, AfterValidator(_unknown)]


class _MultipleOf(IPCRequest):
    value: int = Field(default=2, multiple_of=2)


class _BoundedText(IPCRequest):
    value: str | None = Field(default=None, max_length=3)


class _BoundOnText(IPCRequest):
    value: str = Field(default="b", gt="a")


class _BoundAndValidator(IPCRequest):
    value: Annotated[float, AfterValidator(_unknown)] = Field(default=1.0, gt=0)


class _BoolBound(IPCRequest):
    value: int = Field(default=1, gt=True)


class _Tuple(IPCRequest):
    value: tuple[str, ...] = ()


class _Backtick(IPCRequest):
    value: str = "a`b"


class _Newline(IPCRequest):
    value: str = "a\nb"


class _BacktickLiteral(IPCRequest):
    value: Literal["a`b"] = "a`b"


class _Alias(IPCRequest):
    value: str = Field(default="", alias="other")


class _FieldValidator(IPCRequest):
    value: str = ""

    @field_validator("value")
    @classmethod
    def _keep(cls, v: str) -> str:
        return v


class _ModelValidator(IPCRequest):
    value: str = ""

    @model_validator(mode="after")
    def _keep(self) -> _ModelValidator:
        return self


class _ExtraAllow(IPCRequest):
    model_config = ConfigDict(extra="allow")
    value: str = ""


EXPECTED_CELLS = [
    ("plain", "`plain: str` (필수)"),
    ("number", "`number: int = 60`"),
    ("ratio", "`ratio: float = 1.5`"),
    ("enabled", "`enabled: bool = true`"),
    ("account", "`account: AccountId` (필수)"),
    ("maybe_account", "`maybe_account: AccountId \\| None = null`"),
    ("day", "`day: IsoDate \\| None = null`"),
    ("secret", "`secret: SecretStr` (필수)"),
    ("tags", "`tags: list[str] = []`"),
    ("free", "`free: dict[str, Any] = {}`"),
    ("maybe_free", "`maybe_free: dict[str, Any] \\| None = null`"),
    ("status", '`status: Literal["registered", "adopted"]` (필수)'),
    ("maybe_text", "`maybe_text: str \\| None = null`"),
    ("leaf", "`leaf: _Leaf = _Leaf()`"),
    ("label", '`label: str = "IPC halt"`'),
    ("empty", '`empty: str = ""`'),
    ("positive", "`positive: float \\| None = null` (`> 0`)"),
    ("bounded", "`bounded: int = 1` (`>= 0, <= 10`)"),
    ("below", "`below: float = 0.5` (`< 1.5`)"),
    ("count", "`count: int` (필수) (`> 0`)"),
]


@pytest.mark.parametrize(("name", "expected"), EXPECTED_CELLS)
def test_field_cell_per_branch(name: str, expected: str) -> None:
    assert gen.field_cell(name, _Branches.model_fields[name]) == expected


def test_branch_table_covers_every_fixture_field() -> None:
    assert [name for name, _ in EXPECTED_CELLS] == list(_Branches.model_fields)


def test_secret_default_is_not_rendered() -> None:
    cell = gen.field_cell("token", _SecretWithDefault.model_fields["token"])
    assert cell == "`token: SecretStr` (선택)"
    assert "hidden-value" not in cell


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (_UnknownValidator, "value"),
        (_MultipleOf, "value"),
        (_BoundedText, "value"),
        (_BoundOnText, "value"),
        (_BoundAndValidator, "value"),
        (_BoolBound, "value"),
        (_Tuple, "value"),
        (_Backtick, "value"),
        (_Newline, "value"),
        (_BacktickLiteral, "value"),
        (_Alias, "value"),
    ],
)
def test_unsupported_field_fails(model: type[IPCRequest], name: str) -> None:
    with pytest.raises(gen.UnsupportedFieldError):
        gen.field_cell(name, model.model_fields[name])


@pytest.mark.parametrize("model", [_FieldValidator, _ModelValidator, _ExtraAllow])
def test_unsupported_model_fails(model: type[IPCRequest]) -> None:
    with pytest.raises(gen.UnsupportedFieldError):
        gen.fields_cell(model)


def test_nested_models_are_listed_once() -> None:
    assert gen.nested_models([_Branches, _Leaf, _Branches]) == [_Leaf]


def _real_specs() -> list[Any]:
    registry = CommandRegistry()
    register_all_handlers(registry)
    return registry.iter_specs()


def test_rows_match_registered_commands() -> None:
    specs = _real_specs()
    text = gen.render(specs, all_contracts())
    commands, nested = text.split("\n## 중첩 요청 모델\n")
    command_rows = [line for line in commands.splitlines() if line.startswith("| `")]
    nested_rows = [line for line in nested.splitlines() if line.startswith("| `")]
    assert len(specs) > 0
    nested_models = gen.nested_models([spec.request_model for spec in specs])
    assert len(nested_models) > 0
    assert len(nested_rows) == len(nested_models)
    assert len(command_rows) == len(specs)


def test_committed_document_is_current() -> None:
    committed = gen.DEFAULT_OUTPUT.read_text(encoding="utf-8")
    assert gen.render_ipc_commands() == committed


def test_unpathed_commands_are_named_in_the_preamble() -> None:
    specs = _real_specs()
    contracts = list(all_contracts())
    named = {contract.ipc_command for contract in contracts}
    unpathed = sorted(spec.name for spec in specs if spec.name not in named)
    assert unpathed
    preamble = gen.render(specs, contracts).split("\n## 명령\n")[0]
    expected = ", ".join(f"`{name}`" for name in unpathed)
    assert f"없는 등록 명령({expected})" in preamble


def test_render_is_independent_of_registration_order() -> None:
    specs = _real_specs()
    contracts = list(all_contracts())
    forward = gen.render(specs, contracts)
    backward = gen.render(list(reversed(specs)), list(reversed(contracts)))
    assert forward == backward
    assert gen.render_ipc_commands() == gen.render_ipc_commands()


def _run(*args: str, home: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "ANTE_CONFIG_DIR"}
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), *args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_exit_codes(tmp_path: Path) -> None:
    output = tmp_path / "ipc-commands.md"
    assert _run("--output", str(output), home=tmp_path).returncode == 0
    assert _run("--check", "--output", str(output), home=tmp_path).returncode == 0
    lines = output.read_text(encoding="utf-8").splitlines(keepends=True)
    row = next(i for i, line in enumerate(lines) if line.startswith("| `"))
    lines[row] = lines[row].replace("mutating", "read-only", 1)
    output.write_text("".join(lines), encoding="utf-8")
    stale = _run("--check", "--output", str(output), home=tmp_path)
    assert stale.returncode == 1
    assert "is stale." in stale.stdout
    missing = _run("--check", "--output", str(tmp_path / "absent.md"), home=tmp_path)
    assert missing.returncode == 1
