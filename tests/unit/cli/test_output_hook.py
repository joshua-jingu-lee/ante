"""CLI 출력 훅 (#2751) — ``CommandResult`` 를 계약대로 직렬화한다.

훅(:func:`ante.cli.middleware._emit_command_result`)은 루트
``AuthenticatedGroup.invoke`` 가 돌려받은 값을 본다.

- ``CommandResult`` 가 아니면(``None`` 포함) 아무것도 하지 않는다.
- ``CommandResult`` 이고 계약의 ``envelope`` 이 ``standard`` 면 직렬화한다.
- ``CommandResult`` 인데 계약이 ``raw_legacy`` 이거나 없으면 ``TypeError``.

계약 불일치의 ``TypeError`` 는 런타임에서는 명령의 부수효과가 끝난 뒤에
나므로, 여기서는 훅 함수를 직접 불러 가짜 계약으로 확인한다.
"""

from __future__ import annotations

import dataclasses
import inspect
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.formatter import CommandResult, OutputFormatter
from ante.cli.middleware import _emit_command_result
from ante.contracts.cli_registry import (
    AuthContract,
    CliCommandContract,
    OutputContract,
    get_contract,
)
from ante.contracts.vocab import EnvelopeForm

_PATH = ("fake", "leaf")


def _contract(
    envelope: EnvelopeForm = "standard", data_key: str | None = None
) -> CliCommandContract:
    return CliCommandContract(
        path=_PATH,
        auth=AuthContract(mode="authenticated"),
        output=OutputContract(kind="raw", envelope=envelope, data_key=data_key),
        execution="offline",
    )


def _ctx(mode: str) -> click.Context:
    return click.Context(
        click.Command("leaf"),
        obj={"_leaf_command_path": _PATH, "formatter": OutputFormatter(mode)},
    )


def _emit(rv: object, mode: str, contract: CliCommandContract | None) -> None:
    with patch("ante.cli.middleware.get_contract", return_value=contract) as lookup:
        _emit_command_result(_ctx(mode), rv)
    if isinstance(rv, CommandResult):
        lookup.assert_called_once_with(_PATH)
    else:
        lookup.assert_not_called()


def _envelope(message: str, data: dict[str, Any]) -> str:
    runner = CliRunner()

    @click.command()
    def _ref() -> None:
        OutputFormatter("json").success(message, data)

    return runner.invoke(_ref).output


class TestCommandResult:
    def test_defaults(self) -> None:
        first = CommandResult()
        second = CommandResult()
        assert first.data == {}
        assert first.message == ""
        assert first.text is None
        assert first.data is not second.data

    def test_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(CommandResult(), "message", "x")

    def test_text_str_is_type_error(self) -> None:
        text: Any = "한 줄"
        with pytest.raises(TypeError, match="not a str"):
            CommandResult(text=text)

    def test_text_empty_tuple_is_type_error(self) -> None:
        with pytest.raises(TypeError, match="non-empty"):
            CommandResult(text=())

    @pytest.mark.parametrize("text", [None, ("",), ("a", "b")])
    def test_text_none_or_lines_is_accepted(self, text: tuple[str, ...] | None) -> None:
        assert CommandResult(text=text).text == text


class TestStandardContract:
    def test_json_is_success_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        _emit(CommandResult(data={"a": 1}, message="완료"), "json", _contract())
        assert capsys.readouterr().out == _envelope("완료", {"a": 1})

    def test_json_ignores_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        rv = CommandResult(data={"a": 1}, message="완료", text=("줄",))
        _emit(rv, "json", _contract())
        assert capsys.readouterr().out == _envelope("완료", {"a": 1})

    def test_json_empty_message_and_data(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _emit(CommandResult(), "json", _contract())
        assert capsys.readouterr().out == (
            '{\n  "status": "ok",\n  "message": "",\n  "data": {}\n}\n'
        )

    def test_text_without_lines_is_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _emit(CommandResult(data={"a": 1}, message="완료"), "text", _contract())
        assert capsys.readouterr().out == "완료\n"

    def test_text_lines_are_echoed_in_order(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rv = CommandResult(message="무시", text=("\n제목", "-" * 3, "  끝"))
        _emit(rv, "text", _contract())
        assert capsys.readouterr().out == "\n제목\n---\n  끝\n"

    def test_list_with_data_key_is_wrapped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rv = CommandResult(data=[{"id": 1}, {"id": 2}])
        _emit(rv, "json", _contract(data_key="bots"))
        assert capsys.readouterr().out == _envelope(
            "", {"bots": [{"id": 1}, {"id": 2}]}
        )

    def test_list_without_data_key_is_type_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(TypeError, match="data_key"):
            _emit(CommandResult(data=[1]), "json", _contract())
        assert capsys.readouterr().out == ""


class TestContractMismatch:
    @pytest.mark.parametrize("mode", ["text", "json"])
    def test_raw_legacy_is_type_error(
        self, mode: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(TypeError, match="raw_legacy"):
            _emit(CommandResult(message="m"), mode, _contract("raw_legacy"))
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("mode", ["text", "json"])
    def test_missing_contract_is_type_error(
        self, mode: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(TypeError, match="contract"):
            _emit(CommandResult(message="m"), mode, None)
        assert capsys.readouterr().out == ""


class TestNotCommandResult:
    @pytest.mark.parametrize(
        "rv",
        [None, {"status": "ok", "message": "m", "data": {}}, [1], "m", 0, True],
        ids=["none", "dict", "list", "str", "int", "bool"],
    )
    @pytest.mark.parametrize("contract", ["standard", "raw_legacy", None])
    def test_no_output(
        self,
        rv: object,
        contract: EnvelopeForm | None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _contract(contract) if contract else None
        for mode in ("text", "json"):
            _emit(rv, mode, fake)
        assert capsys.readouterr().out == ""


class TestThroughCli:
    """``--format`` 의 위치(루트·하위)와 상관없이 훅이 leaf 결과를 낸다."""

    @pytest.fixture(autouse=True)
    def _account_doubles(self) -> Any:
        from ante.member.models import Member, MemberRole, MemberStatus, MemberType

        member = Member(
            member_id="tester",
            name="테스터",
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            status=MemberStatus.ACTIVE,
            scopes=[],
        )
        svc = AsyncMock()

        @asynccontextmanager
        async def _service(ctx: Any = None) -> Any:
            yield svc

        with (
            patch(
                "ante.cli.main.authenticate_member",
                side_effect=lambda ctx: ctx.obj.update({"member": member}),
            ),
            patch("ante.cli.commands.account._create_account_service", new=_service),
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_output_hook_test__.sock",
            ),
        ):
            yield

    @pytest.mark.parametrize(
        "args",
        [
            ["--format", "json", "account", "delete", "acct1", "--yes"],
            ["account", "delete", "acct1", "--yes", "--format", "json"],
        ],
        ids=["root", "leaf"],
    )
    def test_format_json_position(self, args: list[str]) -> None:
        from ante.cli.main import cli

        result = CliRunner().invoke(
            cli, args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        assert result.output == _envelope('계좌 "acct1" 삭제 완료', {})

    def test_text_default(self) -> None:
        from ante.cli.main import cli

        result = CliRunner().invoke(
            cli,
            ["account", "delete", "acct1", "--yes"],
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert result.output == '계좌 "acct1" 삭제 완료\n'


def _iter_leaves(
    group: click.Group, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], click.Command]]:
    leaves: list[tuple[tuple[str, ...], click.Command]] = []
    for name, cmd in group.commands.items():
        path = (*prefix, name)
        if isinstance(cmd, click.Group):
            leaves.extend(_iter_leaves(cmd, path))
        else:
            leaves.append((path, cmd))
    return leaves


def _returns_command_result(callback: Any) -> bool:
    annotation = inspect.unwrap(callback).__annotations__.get("return")
    return annotation is CommandResult or annotation == "CommandResult"


def test_command_result_leaves_have_standard_contracts() -> None:
    """반환 주석이 ``CommandResult`` 인 leaf의 계약은 전부 ``standard`` 다."""
    from ante.cli.main import cli

    checked = []
    for path, cmd in _iter_leaves(cli):
        if cmd.callback is None or not _returns_command_result(cmd.callback):
            continue
        contract = get_contract(path)
        assert contract is not None, f"{path}: CommandResult를 돌려주는데 계약이 없다"
        assert contract.output.envelope == "standard", (
            f"{path}: CommandResult를 돌려주는데 계약이 {contract.output.envelope!r}다"
        )
        checked.append(path)
    assert checked, "반환 주석이 CommandResult인 leaf가 하나도 없다(검사가 비었다)"
