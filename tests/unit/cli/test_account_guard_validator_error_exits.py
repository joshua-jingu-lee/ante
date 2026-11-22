"""``account``의 cold-path 가드와 신규 ``account_id`` 검증의 실패 경로 (#2738 ⑧-1).

#2664 ⑦의 특성 테스트가 두 모드로 지나지 않던 출구를 두 모드로 잠근다. 기대값은
리터럴이다. JSON은 stdout 전체를 사전으로, text는 stdout·stderr 전체를 비교한다.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_ACTIVE = "ante.cli.cold_path.is_active_runtime"
_GUARD_CODE = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
_GUARD_MESSAGE = (
    "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER: 서버가 실행 중입니다. "
    "cold-path 명령은 서버 정지 상태에서만 실행할 수 있습니다."
)
_GUARD_LINE = (
    "Error: ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER: 서버가 실행 중입니다. "
    "cold-path 명령은 서버 정지 상태에서만 실행할 수 있습니다.\n"
)
_CREATE = [
    "account",
    "create",
    "--broker-type",
    "test",
    "--name",
    "계좌 9",
    "--trading-mode",
    "virtual",
    "--credential",
    "app_key=fake-k0",
    "--credential",
    "app_secret=fake-s0",
]


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(mode: str, args: list[str], *, active: bool) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        stack.enter_context(patch(_ACTIVE, return_value=active))
        return runner.invoke(cli, ["--format", mode, *args])


def _assert_json(result: Result, code: str, message: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {
        "status": "error",
        "code": code,
        "message": message,
    }
    assert result.stderr == ""


def _assert_text(result: Result, stderr: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr == stderr


_GUARDED = [
    pytest.param([*_CREATE, "--account-id", "acct-9"], id="create"),
    pytest.param(["account", "delete", "acct-9", "--yes"], id="delete"),
    pytest.param(
        ["account", "set-credentials", "acct-9", "--credential", "app_key=fake-k0"],
        id="set-credentials",
    ),
    pytest.param(
        ["account", "repair-timezone", "acct-9", "Asia/Seoul"], id="repair-timezone"
    ),
]


def test_guarded_commands_are_the_four_cold_path_commands() -> None:
    assert len(_GUARDED) == 4


@pytest.mark.parametrize("args", _GUARDED)
def test_cold_path_guard_json(args: list[str]) -> None:
    result = _invoke("json", args, active=True)
    _assert_json(result, _GUARD_CODE, _GUARD_MESSAGE)


@pytest.mark.parametrize("args", _GUARDED)
def test_cold_path_guard_text(args: list[str]) -> None:
    result = _invoke("text", args, active=True)
    _assert_text(result, _GUARD_LINE)


_NEW_IDS = [
    pytest.param(
        "default",
        "(cli.account.create) account_id 'default'는 fallback 예약어로 신규 생성이 "
        "불가합니다.",
        id="default",
    ),
    pytest.param(
        "bad_id",
        "(cli.account.create) account_id 형식이 올바르지 않습니다: 'bad_id'. "
        "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다.",
        id="bad_id",
    ),
    pytest.param(
        "test",
        "(cli.account.create) account_id 'test'는 ante init이 생성하는 시드 계좌로 "
        "예약되어 있어 신규 생성이 불가합니다.",
        id="test",
    ),
]


@pytest.mark.parametrize(("account_id", "message"), _NEW_IDS)
def test_create_invalid_new_account_id_json(account_id: str, message: str) -> None:
    result = _invoke("json", [*_CREATE, "--account-id", account_id], active=False)
    _assert_json(result, "VALIDATION_ERROR", message)


@pytest.mark.parametrize(("account_id", "message"), _NEW_IDS)
def test_create_invalid_new_account_id_text(account_id: str, message: str) -> None:
    result = _invoke("text", [*_CREATE, "--account-id", account_id], active=False)
    _assert_text(result, f"Error: {message}\n")


def test_secret_values_stay_out_of_the_guard_and_validator_exits() -> None:
    results = [
        _invoke(mode, [*_CREATE, "--account-id", account_id], active=active)
        for mode in ("json", "text")
        for account_id, active in (("acct-9", True), ("bad_id", False))
    ]
    assert len(results) == 4
    for result in results:
        assert result.exit_code == 1
        for secret in ("fake-k0", "fake-s0"):
            assert secret not in result.stdout
            assert secret not in result.stderr
