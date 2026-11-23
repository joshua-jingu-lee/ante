"""``account``·``member`` 명령의 실패 경로 특성 테스트 (#2664 PR ⑦).

출구마다 JSON·text 두 모드를 지난다. 기대값은 리터럴이다. JSON은 stdout 전체를
사전으로, text는 stdout·stderr의 줄 전체를 비교한다. 테스트가 넣는 비밀값은 짧은
가짜 표지 문자열이고, 오류 출력에 실리지 않는 것을 따로 단언한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountDeletedError,
    AccountHasActiveBotsError,
    AccountNotFoundError,
    AccountStructuralChangeRequiresStoppedServerError,
)
from ante.account.models import Account, TradingMode
from ante.cli.main import cli
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.member.errors import (
    MemberAlreadyExistsError,
    MemberInvalidRecoveryCredentialError,
    MemberNotFoundError,
    MemberStateConflictError,
    PermissionDeniedError,
)
from ante.member.models import Member, MemberRole, MemberType
from ante.member.scopes import InvalidScopeError

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_ACCOUNT = "acct-9"
_MEMBER = "agent-7"
_SECRET = "SECRETMARK7"
_PASSWORD = "PWMARK7"
_RECOVERY = "RKMARK7"
_SERVER_DOWN = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
_TIMEOUT = "서버 응답 시간 초과"
_IPC_SEND = "ante.cli.commands.ipc_helpers.ipc_send"
_ACTIVE = "ante.cli.cold_path.is_active_runtime"
_ACCOUNT_CM = "ante.cli.commands.account._create_account_service"
_MEMBER_CM = "ante.cli.commands.member._create_service"
_MODES = ("json", "text")
_MASTER_REQUIRED = "권한이 없습니다: master만 수행할 수 있습니다."
_ENV_SLOT = "fake-secret-in-env-slot"
_PATH_SLOT = "/nonexistent-ante-fake"


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(
    args: list[str], *patches: Any, env: dict[str, str] | None = None
) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args, env=env)


def _envelope(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


def _assert_exit(mode: str, result: Result, code: str, message: str, line: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    if mode == "json":
        assert json.loads(result.stdout) == _envelope(code, message)
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert result.stderr.splitlines() == line.splitlines()


def _assert_plain(mode: str, result: Result, code: str, message: str) -> None:
    _assert_exit(mode, result, code, message, f"Error: {message}")


def _assert_coded(mode: str, result: Result, code: str, message: str) -> None:
    _assert_exit(mode, result, code, message, f"Error: {code}: {message}")


def _assert_no_secret(result: Result, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in result.stdout
        assert secret not in result.stderr


def _send(error: BaseException | None = None, value: Any = None) -> Any:
    return patch(_IPC_SEND, new=AsyncMock(side_effect=error, return_value=value))


def _service_cm(target: str, service: Any) -> Any:
    @asynccontextmanager
    async def _open(ctx: object = None) -> AsyncIterator[Any]:
        yield service

    return patch(target, new=_open)


def _account(**overrides: Any) -> Account:
    values: dict[str, Any] = {
        "account_id": _ACCOUNT,
        "name": "계좌 9",
        "exchange": "TEST",
        "currency": "KRW",
        "broker_type": "test",
        "trading_mode": TradingMode.VIRTUAL,
    }
    values.update(overrides)
    return Account(**values)


def _account_service(**methods: Any) -> MagicMock:
    service = MagicMock()
    for name, value in methods.items():
        setattr(service, name, AsyncMock(side_effect=value))
    return service


# ---------------------------------------------------------------- account create


_CREATE = [
    "account",
    "create",
    "--broker-type",
    "test",
    "--account-id",
    _ACCOUNT,
    "--name",
    "계좌 9",
    "--trading-mode",
    "virtual",
]
_CRED_OK = ["--credential", f"app_key={_SECRET}", "--credential", "app_secret=fake-s1"]


_NOT_KEY_VALUE = "{} 옵션의 {}번째 인자가 key=value 형식이 아닙니다."
_EMPTY_KEY = "{} 옵션의 {}번째 인자의 key가 비어 있습니다."
_UNKNOWN_KEY = (
    "알 수 없는 credential key입니다 ({} 옵션의 {}번째 인자). "
    "허용되는 key: ['app_key', 'app_secret']"
)
_ENV_NOT_SET = (
    "--credential-env 옵션의 {}번째 인자({})가 가리키는 환경변수가 "
    "설정되지 않았거나 공란입니다."
)
_FILE_FAILED = "--credential-file 옵션의 {}번째 인자({})가 가리키는 파일{}"
_BROKER_DUP = "--broker-config 옵션의 {}번째 인자의 key가 {}번째 인자와 중복됩니다."


def _create_case(extra: list[str], code: str, message: str, case_id: str) -> Any:
    return pytest.param(extra, code, message, id=case_id)


_CREATE_INPUT_EXITS = [
    _create_case(
        ["--credential", f"app_key{_SECRET}"],
        "CLI_MISSING_REQUIRED_INPUT",
        _NOT_KEY_VALUE.format("--credential", 1),
        "credential-no-equals",
    ),
    _create_case(
        ["--credential", f"app_key={_SECRET}", "--credential", f"app_secret{_SECRET}"],
        "CLI_MISSING_REQUIRED_INPUT",
        _NOT_KEY_VALUE.format("--credential", 2),
        "credential-no-equals-second",
    ),
    _create_case(
        ["--credential", "=fake-v0"],
        "CLI_MISSING_REQUIRED_INPUT",
        _EMPTY_KEY.format("--credential", 1),
        "credential-empty-key",
    ),
    _create_case(
        ["--credential", f"={_SECRET}"],
        "CLI_MISSING_REQUIRED_INPUT",
        _EMPTY_KEY.format("--credential", 1),
        "credential-empty-key-secret",
    ),
    _create_case(
        ["--credential", f"{_SECRET}="],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential", 1),
        "credential-secret-as-key-empty-value",
    ),
    _create_case(
        ["--credential", f"{_SECRET}=x"],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential", 1),
        "credential-secret-as-key",
    ),
    _create_case(
        ["--credential", f"{_SECRET}=="],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential", 1),
        "credential-padded-secret-as-key",
    ),
    _create_case(
        ["--credential", f"app_key={_SECRET}", "--credential", "nope="],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential", 2),
        "credential-unknown-key-second",
    ),
    _create_case(
        ["--credential", "app_key="],
        "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
        "--credential app_key: 값이 비어 있습니다. "
        "credential 값은 비어 있을 수 없습니다.",
        "credential-empty-value",
    ),
    _create_case(
        ["--credential", f"nope={_SECRET}"],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential", 1),
        "credential-unknown-key",
    ),
    _create_case(
        [
            "--credential-env",
            "app_key=FAKE_ENV_A",
            "--credential-env",
            f"{_SECRET}=FAKE_ENV_UNSET",
        ],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential-env", 2),
        "credential-env-secret-as-key",
    ),
    _create_case(
        ["--credential-env", "nope="],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential-env", 1),
        "credential-env-unknown-key-empty-name",
    ),
    _create_case(
        ["--credential-file", f"{_SECRET}=/p"],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential-file", 1),
        "credential-file-secret-as-key",
    ),
    _create_case(
        ["--credential-file", "nope=/nonexistent-ante-fake/cred.txt"],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential-file", 1),
        "credential-file-unknown-key-not-read",
    ),
    _create_case(
        ["--credential-file", "nope="],
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        _UNKNOWN_KEY.format("--credential-file", 1),
        "credential-file-unknown-key-empty-path",
    ),
    _create_case(
        [
            "--credential",
            f"app_key={_SECRET}",
            "--credential-env",
            "app_key=FAKE_ENV_A",
        ],
        "ACCOUNT_DUPLICATE_CREDENTIAL_KEY",
        "credential key 'app_key'가 둘 이상 채널로 중복 입력되었습니다.",
        "credential-duplicate",
    ),
    _create_case(
        ["--credential-env", "app_key="],
        "CLI_MISSING_REQUIRED_INPUT",
        "--credential-env app_key의 환경변수 이름이 비어 있습니다.",
        "credential-env-empty-name",
    ),
    _create_case(
        ["--credential-env", "app_key=FAKE_ENV_UNSET"],
        "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
        _ENV_NOT_SET.format(1, "app_key"),
        "credential-env-unset",
    ),
    _create_case(
        ["--credential-env", f"app_key={_ENV_SLOT}"],
        "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
        _ENV_NOT_SET.format(1, "app_key"),
        "credential-env-value-in-name-slot",
    ),
    _create_case(
        [
            "--credential-env",
            "app_key=FAKE_ENV_A",
            "--credential-env",
            f"app_secret={_ENV_SLOT}",
        ],
        "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
        _ENV_NOT_SET.format(2, "app_secret"),
        "credential-env-unset-second",
    ),
    _create_case(
        ["--credential-file", "app_key="],
        "CLI_MISSING_REQUIRED_INPUT",
        "--credential-file app_key의 파일 경로가 비어 있습니다.",
        "credential-file-empty-path",
    ),
    _create_case(
        ["--credential-file", f"app_key={_PATH_SLOT}/cred.txt"],
        "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
        _FILE_FAILED.format(1, "app_key", "을 찾을 수 없습니다."),
        "credential-file-missing",
    ),
    _create_case(
        [
            "--credential-env",
            "app_key=FAKE_ENV_A",
            "--credential-file",
            f"app_secret={_PATH_SLOT}/{_ENV_SLOT}",
        ],
        "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
        _FILE_FAILED.format(1, "app_secret", "을 찾을 수 없습니다."),
        "credential-file-missing-value-in-path-slot",
    ),
    _create_case(
        ["--credential", f"app_key={_SECRET}"],
        "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
        "필수 credential 누락: ['app_secret']. --credential / --credential-env / "
        "--credential-file 중 하나로 모두 제공해야 합니다.",
        "credential-missing-required",
    ),
    _create_case(
        [*_CRED_OK, "--broker-config", "is_paper"],
        "CLI_MISSING_REQUIRED_INPUT",
        _NOT_KEY_VALUE.format("--broker-config", 1),
        "broker-config-no-equals",
    ),
    _create_case(
        [*_CRED_OK, "--broker-config", "a=1", "--broker-config", "=fake-v0"],
        "CLI_MISSING_REQUIRED_INPUT",
        _EMPTY_KEY.format("--broker-config", 2),
        "broker-config-empty-key-second",
    ),
    _create_case(
        [*_CRED_OK, "--broker-config", "fake-v1=1", "--broker-config", "fake-v1=2"],
        "CLI_MISSING_REQUIRED_INPUT",
        _BROKER_DUP.format(2, 1),
        "broker-config-duplicate",
    ),
    _create_case(
        [
            *_CRED_OK,
            "--broker-config",
            "a=1",
            "--broker-config",
            "fake-v1=1",
            "--broker-config",
            "fake-v1=2",
        ],
        "CLI_MISSING_REQUIRED_INPUT",
        _BROKER_DUP.format(3, 2),
        "broker-config-duplicate-later",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("extra", "code", "message"), _CREATE_INPUT_EXITS)
def test_account_create_input_exit(
    mode: str, extra: list[str], code: str, message: str
) -> None:
    service = _account_service(create=AssertionError("서비스에 닿으면 안 된다"))
    result = _invoke(
        ["--format", mode, *_CREATE, *extra],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, service),
        env={"FAKE_ENV_A": "fake-env-v", "FAKE_ENV_UNSET": ""},
    )
    _assert_exit(mode, result, code, f"{code}: {message}", f"Error: {code}: {message}")
    _assert_no_secret(
        result,
        _SECRET,
        "fake-s1",
        "fake-env-v",
        "fake-v0",
        "fake-v1",
        _ENV_SLOT,
        _PATH_SLOT,
        "FAKE_ENV_UNSET",
    )
    service.create.assert_not_called()


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_credential_file_unreadable(mode: str, tmp_path: Path) -> None:
    folder = tmp_path / "cred-dir"
    folder.mkdir()
    result = _invoke(
        ["--format", mode, *_CREATE, "--credential-file", f"app_key={folder}"],
        patch(_ACTIVE, return_value=False),
    )
    message = "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: " + _FILE_FAILED.format(
        1, "app_key", "을 읽을 수 없습니다."
    )
    _assert_plain(mode, result, "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND", message)
    _assert_no_secret(result, str(tmp_path), "Errno")


_UNDECODABLE = b"fake-sec\xff\xfe-tail\n"
_DECODE_TRACES = ("0xff", "0xfe", "codec", "position", "fake-sec")


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_credential_file_undecodable(mode: str, tmp_path: Path) -> None:
    secret_file = tmp_path / "cred.bin"
    secret_file.write_bytes(_UNDECODABLE)
    result = _invoke(
        ["--format", mode, *_CREATE, "--credential-file", f"app_key={secret_file}"],
        patch(_ACTIVE, return_value=False),
    )
    message = "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: " + _FILE_FAILED.format(
        1, "app_key", "을 읽을 수 없습니다."
    )
    _assert_plain(mode, result, "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND", message)
    _assert_no_secret(result, *_DECODE_TRACES, str(tmp_path))


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_credential_file_empty(mode: str, tmp_path: Path) -> None:
    empty = tmp_path / "cred.txt"
    empty.write_text("\n", encoding="utf-8")
    result = _invoke(
        ["--format", mode, *_CREATE, "--credential-file", f"app_key={empty}"],
        patch(_ACTIVE, return_value=False),
    )
    message = "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: " + _FILE_FAILED.format(
        1, "app_key", "이 비어 있습니다."
    )
    _assert_plain(mode, result, "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND", message)
    _assert_no_secret(result, str(tmp_path))


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_credential_file_secret_stays_out(
    mode: str, tmp_path: Path
) -> None:
    secret_file = tmp_path / "cred.txt"
    secret_file.write_text(f"{_SECRET}\n", encoding="utf-8")
    result = _invoke(
        [
            "--format",
            mode,
            *_CREATE,
            "--credential-file",
            f"app_key={secret_file}",
            "--credential",
            "app_key=fake-k2",
        ],
        patch(_ACTIVE, return_value=False),
    )
    message = (
        "ACCOUNT_DUPLICATE_CREDENTIAL_KEY: credential key 'app_key'가 "
        "둘 이상 채널로 중복 입력되었습니다."
    )
    _assert_plain(mode, result, "ACCOUNT_DUPLICATE_CREDENTIAL_KEY", message)
    _assert_no_secret(result, _SECRET, "fake-k2")


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_missing_required_options(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "account", "create", "--broker-type", "test"],
        patch(_ACTIVE, return_value=False),
    )
    message = (
        "CLI_MISSING_REQUIRED_INPUT: 필수 옵션 누락: "
        "['--account-id', '--name', '--trading-mode']"
    )
    _assert_plain(mode, result, "CLI_MISSING_REQUIRED_INPUT", message)


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_unregistered_broker_type(mode: str) -> None:
    args = list(_CREATE)
    args[3] = "fake-broker"
    result = _invoke(["--format", mode, *args], patch(_ACTIVE, return_value=False))
    message = (
        "CLI_MISSING_REQUIRED_INPUT: 등록되지 않은 broker_type: 'fake-broker'. "
        "허용 값: ['kis-domestic', 'mock', 'test']"
    )
    _assert_plain(mode, result, "CLI_MISSING_REQUIRED_INPUT", message)


@pytest.mark.parametrize("mode", _MODES)
def test_account_create_broker_preset_missing(mode: str) -> None:
    result = _invoke(
        ["--format", mode, *_CREATE, *_CRED_OK],
        patch(_ACTIVE, return_value=False),
        patch.dict("ante.account.presets.BROKER_PRESETS", {}, clear=True),
    )
    message = "CLI_MISSING_REQUIRED_INPUT: broker preset 미정의: 'test'"
    _assert_plain(mode, result, "CLI_MISSING_REQUIRED_INPUT", message)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            RuntimeError("계좌 생성 실패"),
            "EXECUTION_ERROR",
            "계좌 생성 실패",
            id="runtime",
        ),
        pytest.param(
            AccountAlreadyExistsError(f"계좌 '{_ACCOUNT}'가 이미 존재합니다."),
            "ACCOUNT_ALREADY_EXISTS",
            f"계좌 '{_ACCOUNT}'가 이미 존재합니다.",
            id="exists",
        ),
    ],
)
def test_account_create_service_error(
    mode: str, error: BaseException, code: str, message: str
) -> None:
    result = _invoke(
        ["--format", mode, *_CREATE, *_CRED_OK],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, _account_service(create=error)),
    )
    _assert_coded(mode, result, code, message)
    _assert_no_secret(result, _SECRET, "fake-s1")


# ---------------------------------------------------------------- account reads


@pytest.mark.parametrize("mode", _MODES)
def test_account_list_invalid_status(mode: str) -> None:
    service = _account_service(list=AssertionError("서비스에 닿으면 안 된다"))
    result = _invoke(
        ["--format", mode, "account", "list", "--status", "closed"],
        _service_cm(_ACCOUNT_CM, service),
    )
    message = "잘못된 status 값: 'closed'. 허용값: ['active', 'deleted', 'suspended']"
    _assert_coded(mode, result, "ACCOUNT_INVALID_STATUS", message)


_ACCOUNT_READS = [
    pytest.param(["account", "list", "--status", "suspended"], "list", id="list"),
    pytest.param(["account", "info", _ACCOUNT], "get", id="info"),
    pytest.param(["account", "credentials", _ACCOUNT], "get", id="credentials"),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "method"), _ACCOUNT_READS)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            RuntimeError("계좌 조회 실패"),
            "EXECUTION_ERROR",
            "계좌 조회 실패",
            id="runtime",
        ),
        pytest.param(
            AccountNotFoundError(f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다."),
            "ACCOUNT_NOT_FOUND",
            f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다.",
            id="not-found",
        ),
    ],
)
def test_account_read_service_error(
    mode: str,
    args: list[str],
    method: str,
    error: BaseException,
    code: str,
    message: str,
) -> None:
    result = _invoke(
        ["--format", mode, *args],
        _service_cm(_ACCOUNT_CM, _account_service(**{method: error})),
    )
    _assert_coded(mode, result, code, message)


# ---------------------------------------------------------------- account IPC


_ACCOUNT_IPC = [
    pytest.param(["account", "suspend", _ACCOUNT], id="suspend"),
    pytest.param(["account", "activate", _ACCOUNT], id="activate"),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _ACCOUNT_IPC)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}",
            id="down",
        ),
        pytest.param(
            IPCClientTimeoutError(_TIMEOUT),
            "IPC_TIMEOUT",
            _TIMEOUT,
            f"Error: IPC_TIMEOUT: {_TIMEOUT}",
            id="timeout",
        ),
        pytest.param(
            IPCRemoteError("ACCOUNT_NOT_FOUND", "계좌를 찾을 수 없습니다"),
            "ACCOUNT_NOT_FOUND",
            "계좌를 찾을 수 없습니다",
            "Error: ACCOUNT_NOT_FOUND: 계좌를 찾을 수 없습니다",
            id="remote",
        ),
        pytest.param(
            RuntimeError("소켓 끊김"),
            "EXECUTION_ERROR",
            "소켓 끊김",
            "Error: EXECUTION_ERROR: 소켓 끊김",
            id="runtime",
        ),
    ],
)
def test_account_ipc_error(
    mode: str,
    args: list[str],
    error: BaseException,
    code: str,
    message: str,
    line: str,
) -> None:
    result = _invoke(["--format", mode, *args], _send(error))
    _assert_exit(mode, result, code, message, line)


# ---------------------------------------------------------------- account delete


@pytest.mark.parametrize("mode", _MODES)
def test_account_delete_requires_confirmation(mode: str) -> None:
    service = _account_service(delete=AssertionError("서비스에 닿으면 안 된다"))
    result = _invoke(
        ["--format", mode, "account", "delete", _ACCOUNT],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, service),
    )
    message = (
        'CLI_CONFIRMATION_REQUIRED: 계좌 "acct-9" 삭제는 확인이 필요합니다. '
        "--yes를 명시해 주세요."
    )
    _assert_plain(mode, result, "CLI_CONFIRMATION_REQUIRED", message)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            AccountHasActiveBotsError(_ACCOUNT, 2),
            "ACCOUNT_HAS_ACTIVE_BOTS",
            str(AccountHasActiveBotsError(_ACCOUNT, 2)),
            id="active-bots",
        ),
        pytest.param(
            AccountNotFoundError(f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다."),
            "ACCOUNT_NOT_FOUND",
            f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다.",
            id="not-found",
        ),
        pytest.param(
            AccountDeletedError(f"계좌 '{_ACCOUNT}'는 이미 삭제되었습니다."),
            "ACCOUNT_ALREADY_DELETED",
            f"계좌 '{_ACCOUNT}'는 이미 삭제되었습니다.",
            id="already-deleted",
        ),
        pytest.param(
            RuntimeError("계좌 삭제 실패"),
            "EXECUTION_ERROR",
            "계좌 삭제 실패",
            id="runtime",
        ),
    ],
)
def test_account_delete_service_error(
    mode: str, error: BaseException, code: str, message: str
) -> None:
    result = _invoke(
        ["--format", mode, "account", "delete", _ACCOUNT, "--yes"],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, _account_service(delete=error)),
    )
    _assert_coded(mode, result, code, message)


# ---------------------------------------------------------------- set-credentials


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("broker_type", "extra", "code", "message"),
    [
        pytest.param(
            "mock",
            ["--credential", f"app_key={_SECRET}"],
            "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
            "브로커 'mock'은 credentials를 요구하지 않습니다.",
            id="no-credentials-broker",
        ),
        pytest.param(
            "test",
            [],
            "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
            "credential 옵션이 누락되었습니다. --credential / --credential-env / "
            "--credential-file 중 하나로 required keys ['app_key', 'app_secret']를 "
            "모두 제공해야 합니다.",
            id="no-input",
        ),
        pytest.param(
            "test",
            ["--credential", f"nope={_SECRET}"],
            "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
            _UNKNOWN_KEY.format("--credential", 1),
            id="unknown-key",
        ),
        pytest.param(
            "test",
            ["--credential", f"app_key{_SECRET}"],
            "CLI_MISSING_REQUIRED_INPUT",
            _NOT_KEY_VALUE.format("--credential", 1),
            id="no-equals",
        ),
        pytest.param(
            "test",
            ["--credential", f"{_SECRET}="],
            "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
            _UNKNOWN_KEY.format("--credential", 1),
            id="secret-as-key",
        ),
        pytest.param(
            "test",
            ["--credential-env", f"app_key={_ENV_SLOT}"],
            "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
            _ENV_NOT_SET.format(1, "app_key"),
            id="env-value-in-name-slot",
        ),
    ],
)
def test_account_set_credentials_input_exit(
    mode: str, broker_type: str, extra: list[str], code: str, message: str
) -> None:
    service = _account_service(
        get=[_account(broker_type=broker_type)],
        update=AssertionError("갱신에 닿으면 안 된다"),
    )
    result = _invoke(
        ["--format", mode, "account", "set-credentials", _ACCOUNT, *extra],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, service),
    )
    _assert_exit(mode, result, code, f"{code}: {message}", f"Error: {code}: {message}")
    _assert_no_secret(result, _SECRET, _ENV_SLOT)
    service.update.assert_not_called()


@pytest.mark.parametrize("mode", _MODES)
def test_account_set_credentials_credential_file_undecodable(
    mode: str, tmp_path: Path
) -> None:
    secret_file = tmp_path / "cred.bin"
    secret_file.write_bytes(_UNDECODABLE)
    service = _account_service(
        get=[_account()],
        update=AssertionError("갱신에 닿으면 안 된다"),
    )
    result = _invoke(
        [
            "--format",
            mode,
            "account",
            "set-credentials",
            _ACCOUNT,
            "--credential-file",
            f"app_key={secret_file}",
        ],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, service),
    )
    message = "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: " + _FILE_FAILED.format(
        1, "app_key", "을 읽을 수 없습니다."
    )
    _assert_plain(mode, result, "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND", message)
    _assert_no_secret(result, *_DECODE_TRACES, str(tmp_path))
    service.update.assert_not_called()


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            RuntimeError("인증 정보 저장 실패"),
            "EXECUTION_ERROR",
            "인증 정보 저장 실패",
            id="runtime",
        ),
        pytest.param(
            AccountNotFoundError(f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다."),
            "ACCOUNT_NOT_FOUND",
            f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다.",
            id="not-found",
        ),
    ],
)
def test_account_set_credentials_service_error(
    mode: str, error: BaseException, code: str, message: str
) -> None:
    service = _account_service(get=[_account()], update=error)
    result = _invoke(
        ["--format", mode, "account", "set-credentials", _ACCOUNT, *_CRED_OK],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, service),
    )
    _assert_coded(mode, result, code, message)
    _assert_no_secret(result, _SECRET, "fake-s1")


# ---------------------------------------------------------------- repair-timezone


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
        pytest.param(
            ValueError("unknown zone"),
            "ACCOUNT_INVALID_TIMEZONE",
            "ACCOUNT_INVALID_TIMEZONE: invalid IANA timezone: 'Mars/Olympus' "
            "— unknown zone",
            "Error: ACCOUNT_INVALID_TIMEZONE: invalid IANA timezone: 'Mars/Olympus' "
            "— unknown zone",
            id="invalid-timezone",
        ),
        pytest.param(
            AccountStructuralChangeRequiresStoppedServerError("서버를 먼저 멈추세요."),
            "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER",
            "서버를 먼저 멈추세요.",
            "Error: ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER: "
            "서버를 먼저 멈추세요.",
            id="structural",
        ),
        pytest.param(
            AccountNotFoundError(f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다."),
            "ACCOUNT_NOT_FOUND",
            f"계좌 '{_ACCOUNT}'를 찾을 수 없습니다.",
            f"Error: ACCOUNT_NOT_FOUND: 계좌 '{_ACCOUNT}'를 찾을 수 없습니다.",
            id="not-found",
        ),
        pytest.param(
            AccountDeletedError(f"계좌 '{_ACCOUNT}'는 이미 삭제되었습니다."),
            "ACCOUNT_ALREADY_DELETED",
            f"계좌 '{_ACCOUNT}'는 이미 삭제되었습니다.",
            f"Error: ACCOUNT_ALREADY_DELETED: 계좌 '{_ACCOUNT}'는 이미 삭제되었습니다.",
            id="already-deleted",
        ),
        pytest.param(
            RuntimeError("복구 실패"),
            "EXECUTION_ERROR",
            "복구 실패",
            "Error: EXECUTION_ERROR: 복구 실패",
            id="runtime",
        ),
    ],
)
def test_account_repair_timezone_error(
    mode: str, error: BaseException, code: str, message: str, line: str
) -> None:
    result = _invoke(
        ["--format", mode, "account", "repair-timezone", _ACCOUNT, "Mars/Olympus"],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, _account_service(repair_timezone=error)),
    )
    _assert_exit(mode, result, code, message, line)


def test_account_repair_timezone_success_keeps_its_code() -> None:
    repaired = _account(timezone="Asia/Seoul")
    result = _invoke(
        ["--format", "json", "account", "repair-timezone", _ACCOUNT, "Asia/Seoul"],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, _account_service(repair_timezone=[repaired])),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {
        "status": "ok",
        "message": '계좌 "acct-9" timezone 복구 완료 (Asia/Seoul)',
        "data": {
            "code": "ACCOUNT_REPAIR_TIMEZONE_OK",
            "account_id": "acct-9",
            "timezone": "Asia/Seoul",
            "timezone_invalid": False,
        },
    }
    assert result.stderr == ""


def test_account_repair_timezone_success_text() -> None:
    repaired = _account(timezone="Asia/Seoul")
    result = _invoke(
        ["--format", "text", "account", "repair-timezone", _ACCOUNT, "Asia/Seoul"],
        patch(_ACTIVE, return_value=False),
        _service_cm(_ACCOUNT_CM, _account_service(repair_timezone=[repaired])),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert result.stdout.splitlines() == [
        '계좌 "acct-9" timezone 복구 완료 (Asia/Seoul)'
    ]
    assert result.stderr == ""


# ---------------------------------------------------------------- member secrets


_SECRET_COMMANDS = [
    pytest.param(
        ["member", "reset-password", "--recovery-key", _RECOVERY],
        "--new-password-env",
        "--new-password-file",
        "새 패스워드 입력이 필요합니다.",
        id="reset-password",
    ),
    pytest.param(
        ["member", "regenerate-recovery-key"],
        "--password-env",
        "--password-file",
        "현재 패스워드 입력이 필요합니다.",
        id="regenerate-recovery-key",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_input_missing(
    mode: str, args: list[str], env_opt: str, file_opt: str, missing: str
) -> None:
    result = _invoke(["--format", mode, *args], _send(AssertionError("IPC 금지")))
    message = f"{missing} {env_opt} 또는 {file_opt} 중 하나를 지정하세요."
    _assert_coded(mode, result, "CLI_MISSING_REQUIRED_INPUT", message)
    _assert_no_secret(result, _RECOVERY)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_input_both(
    mode: str,
    args: list[str],
    env_opt: str,
    file_opt: str,
    missing: str,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "pw.txt"
    secret_file.write_text(_PASSWORD, encoding="utf-8")
    result = _invoke(
        ["--format", mode, *args, env_opt, "FAKE_PW_ENV", file_opt, str(secret_file)],
        _send(AssertionError("IPC 금지")),
        env={"FAKE_PW_ENV": _PASSWORD},
    )
    message = (
        f"{env_opt}와 {file_opt}는 동시에 지정할 수 없습니다. 둘 중 하나만 사용하세요."
    )
    _assert_coded(mode, result, "CLI_MISSING_REQUIRED_INPUT", message)
    _assert_no_secret(result, _PASSWORD, _RECOVERY)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("name", ["FAKE_PW_ENV", _ENV_SLOT])
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_env_not_set(
    mode: str, name: str, args: list[str], env_opt: str, file_opt: str, missing: str
) -> None:
    result = _invoke(
        ["--format", mode, *args, env_opt, name],
        _send(AssertionError("IPC 금지")),
        env={"FAKE_PW_ENV": "   "},
    )
    message = (
        f"{env_opt}가 가리키는 환경변수가 설정되어 있지 않거나 공란입니다. "
        f"{env_opt}는 비밀값이 든 환경변수의 *이름*만 받습니다."
    )
    _assert_coded(mode, result, "MEMBER_PASSWORD_ENV_NOT_SET", message)
    _assert_no_secret(result, _RECOVERY, name)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_file_unreadable(
    mode: str,
    args: list[str],
    env_opt: str,
    file_opt: str,
    missing: str,
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent.txt"
    result = _invoke(
        ["--format", mode, *args, file_opt, str(absent)],
        _send(AssertionError("IPC 금지")),
    )
    message = f"{file_opt} 파일을 읽을 수 없습니다."
    _assert_coded(mode, result, "MEMBER_PASSWORD_FILE_NOT_FOUND", message)
    _assert_no_secret(result, _RECOVERY, str(tmp_path), "Errno")


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_file_undecodable(
    mode: str,
    args: list[str],
    env_opt: str,
    file_opt: str,
    missing: str,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "pw.bin"
    secret_file.write_bytes(_UNDECODABLE)
    result = _invoke(
        ["--format", mode, *args, file_opt, str(secret_file)],
        _send(AssertionError("IPC 금지")),
    )
    message = f"{file_opt} 파일을 읽을 수 없습니다."
    _assert_coded(mode, result, "MEMBER_PASSWORD_FILE_NOT_FOUND", message)
    _assert_no_secret(result, _RECOVERY, *_DECODE_TRACES, str(tmp_path))


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "env_opt", "file_opt", "missing"), _SECRET_COMMANDS)
def test_member_secret_file_empty(
    mode: str,
    args: list[str],
    env_opt: str,
    file_opt: str,
    missing: str,
    tmp_path: Path,
) -> None:
    empty = tmp_path / "pw.txt"
    empty.write_text("  \n", encoding="utf-8")
    result = _invoke(
        ["--format", mode, *args, file_opt, str(empty)],
        _send(AssertionError("IPC 금지")),
    )
    message = f"{file_opt} 파일이 비어 있습니다."
    _assert_coded(mode, result, "MEMBER_PASSWORD_FILE_NOT_FOUND", message)
    _assert_no_secret(result, _RECOVERY, str(tmp_path))


def _secret_args(args: list[str], env_opt: str) -> list[str]:
    return [*args, env_opt, "FAKE_PW_ENV"]


_MASTER_MEMBER = Member(
    member_id="owner-1",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Owner",
    status="active",
    scopes=[],
)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "env_opt", "method"),
    [
        pytest.param(
            ["member", "reset-password", "--recovery-key", _RECOVERY],
            "--new-password-env",
            "reset_password",
            id="reset-password",
        ),
        pytest.param(
            ["member", "regenerate-recovery-key"],
            "--password-env",
            "regenerate_recovery_key",
            id="regenerate-recovery-key",
        ),
    ],
)
@pytest.mark.parametrize(
    ("members", "error", "code", "message"),
    [
        pytest.param(
            [_MASTER_MEMBER],
            MemberInvalidRecoveryCredentialError("복구 자격 증명이 올바르지 않습니다."),
            "MEMBER_INVALID_RECOVERY_CREDENTIAL",
            "복구 자격 증명이 올바르지 않습니다.",
            id="invalid-credential",
        ),
        pytest.param(
            [],
            None,
            "EXECUTION_ERROR",
            "master 멤버가 존재하지 않습니다",
            id="no-master",
        ),
        pytest.param(
            [_MASTER_MEMBER],
            PermissionError("권한 없음"),
            "EXECUTION_ERROR",
            "권한 없음",
            id="permission-error",
        ),
    ],
)
def test_member_secret_cold_path_error(
    mode: str,
    args: list[str],
    env_opt: str,
    method: str,
    members: list[Member],
    error: BaseException | None,
    code: str,
    message: str,
) -> None:
    service = MagicMock()
    service.list_members = AsyncMock(return_value=members)
    setattr(service, method, AsyncMock(side_effect=error))
    result = _invoke(
        ["--format", mode, *_secret_args(args, env_opt)],
        patch(_ACTIVE, return_value=False),
        _send(AssertionError("IPC 금지")),
        _service_cm(_MEMBER_CM, service),
        env={"FAKE_PW_ENV": _PASSWORD},
    )
    _assert_coded(mode, result, code, message)
    _assert_no_secret(result, _PASSWORD, _RECOVERY)


# ---------------------------------------------------------------- member IPC


_IPC_ERRORS = [
    pytest.param(
        IPCServerNotRunningError(_SERVER_DOWN),
        "IPC_SERVER_NOT_RUNNING",
        _SERVER_DOWN,
        f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}",
        id="down",
    ),
    pytest.param(
        IPCClientTimeoutError(_TIMEOUT),
        "IPC_TIMEOUT",
        _TIMEOUT,
        f"Error: IPC_TIMEOUT: {_TIMEOUT}",
        id="timeout",
    ),
    pytest.param(
        IPCRemoteError("MEMBER_NOT_FOUND", "멤버를 찾을 수 없습니다"),
        "MEMBER_NOT_FOUND",
        "멤버를 찾을 수 없습니다",
        "Error: MEMBER_NOT_FOUND: 멤버를 찾을 수 없습니다",
        id="remote",
    ),
]

_MEMBER_COMMANDS = [
    pytest.param(
        ["member", "register", "--id", _MEMBER, "--type", "agent"], id="register"
    ),
    pytest.param(["member", "set-emoji", _MEMBER, "x"], id="set-emoji"),
    pytest.param(
        ["member", "update-scopes", _MEMBER, "--scopes", "bot:read"], id="update-scopes"
    ),
    pytest.param(["member", "suspend", _MEMBER], id="suspend"),
    pytest.param(["member", "reactivate", _MEMBER], id="reactivate"),
    pytest.param(["member", "revoke", _MEMBER, "--yes"], id="revoke"),
    pytest.param(["member", "rotate-token", _MEMBER], id="rotate-token"),
    pytest.param(
        [
            "member",
            "reset-password",
            "--recovery-key",
            _RECOVERY,
            "--new-password-env",
            "FAKE_PW_ENV",
        ],
        id="reset-password",
    ),
    pytest.param(
        ["member", "regenerate-recovery-key", "--password-env", "FAKE_PW_ENV"],
        id="regenerate-recovery-key",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _MEMBER_COMMANDS)
@pytest.mark.parametrize(("error", "code", "message", "line"), _IPC_ERRORS)
def test_member_ipc_error(
    mode: str,
    args: list[str],
    error: BaseException,
    code: str,
    message: str,
    line: str,
) -> None:
    service = MagicMock()
    result = _invoke(
        ["--format", mode, *args],
        patch(_ACTIVE, return_value=True),
        _send(error),
        _service_cm(_MEMBER_CM, service),
        env={"FAKE_PW_ENV": _PASSWORD},
    )
    _assert_exit(mode, result, code, message, line)
    _assert_no_secret(result, _PASSWORD, _RECOVERY)
    assert service.mock_calls == []


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _MEMBER_COMMANDS)
def test_member_ipc_error_skips_the_cold_path(mode: str, args: list[str]) -> None:
    opened: list[object] = []

    @asynccontextmanager
    async def _open(ctx: object = None) -> AsyncIterator[Any]:
        opened.append(ctx)
        yield MagicMock()

    result = _invoke(
        ["--format", mode, *args],
        patch(_ACTIVE, return_value=True),
        _send(IPCServerNotRunningError(_SERVER_DOWN)),
        patch(_MEMBER_CM, new=_open),
        env={"FAKE_PW_ENV": _PASSWORD},
    )
    assert result.exit_code == 1
    assert opened == []


_COLD_METHOD = {
    "register": "register",
    "set-emoji": "update_emoji",
    "update-scopes": "update_scopes",
    "suspend": "suspend",
    "reactivate": "reactivate",
    "revoke": "revoke",
    "rotate-token": "rotate_token",
}


def _cold_case(
    command: str, error: BaseException, code: str, message: str, case_id: str
) -> Any:
    return pytest.param(command, error, code, message, id=f"{command}-{case_id}")


_NOT_FOUND = f"멤버를 찾을 수 없습니다: {_MEMBER}"

_MEMBER_COLD_EXITS = [
    _cold_case(
        "register",
        PermissionDeniedError("x"),
        "PERMISSION_DENIED",
        _MASTER_REQUIRED,
        "denied",
    ),
    _cold_case(
        "register",
        MemberAlreadyExistsError(_MEMBER),
        "MEMBER_ALREADY_EXISTS",
        str(MemberAlreadyExistsError(_MEMBER)),
        "exists",
    ),
    _cold_case(
        "register",
        InvalidScopeError("bot:fly"),
        "MEMBER_INVALID_SCOPE",
        str(InvalidScopeError("bot:fly")),
        "scope",
    ),
    _cold_case(
        "register", ValueError("잘못된 입력"), "EXECUTION_ERROR", "잘못된 입력", "value"
    ),
    _cold_case(
        "register",
        PermissionError("권한 없음"),
        "EXECUTION_ERROR",
        "권한 없음",
        "permission",
    ),
    _cold_case(
        "set-emoji",
        MemberNotFoundError(_MEMBER),
        "MEMBER_NOT_FOUND",
        _NOT_FOUND,
        "not-found",
    ),
    _cold_case(
        "set-emoji",
        ValueError("잘못된 이모지"),
        "EXECUTION_ERROR",
        "잘못된 이모지",
        "value",
    ),
    _cold_case(
        "update-scopes",
        PermissionDeniedError("x"),
        "PERMISSION_DENIED",
        _MASTER_REQUIRED,
        "denied",
    ),
    _cold_case(
        "update-scopes",
        InvalidScopeError("bot:fly"),
        "MEMBER_INVALID_SCOPE",
        str(InvalidScopeError("bot:fly")),
        "scope",
    ),
    _cold_case(
        "update-scopes",
        MemberNotFoundError(_MEMBER),
        "MEMBER_NOT_FOUND",
        str(MemberNotFoundError(_MEMBER)),
        "not-found",
    ),
    _cold_case(
        "update-scopes",
        PermissionError("권한 없음"),
        "EXECUTION_ERROR",
        "권한 없음",
        "permission",
    ),
]
for _command in ("suspend", "reactivate"):
    _MEMBER_COLD_EXITS += [
        _cold_case(
            _command,
            PermissionDeniedError("x"),
            "PERMISSION_DENIED",
            _MASTER_REQUIRED,
            "denied",
        ),
        _cold_case(
            _command,
            MemberNotFoundError(_MEMBER),
            "MEMBER_NOT_FOUND",
            _NOT_FOUND,
            "not-found",
        ),
        _cold_case(
            _command,
            MemberStateConflictError(_MEMBER, "revoked", _command),
            "MEMBER_STATE_CONFLICT",
            str(MemberStateConflictError(_MEMBER, "revoked", _command)),
            "conflict",
        ),
        _cold_case(
            _command,
            ValueError("잘못된 입력"),
            "EXECUTION_ERROR",
            "잘못된 입력",
            "value",
        ),
    ]
for _command in ("revoke", "rotate-token"):
    _MEMBER_COLD_EXITS += [
        _cold_case(
            _command,
            PermissionDeniedError("x"),
            "PERMISSION_DENIED",
            _MASTER_REQUIRED,
            "denied",
        ),
        _cold_case(
            _command,
            MemberNotFoundError(_MEMBER),
            "MEMBER_NOT_FOUND",
            _NOT_FOUND,
            "not-found",
        ),
        _cold_case(
            _command,
            PermissionError("권한 없음"),
            "EXECUTION_ERROR",
            "권한 없음",
            "permission",
        ),
    ]

_COLD_ARGS = {
    "register": ["member", "register", "--id", _MEMBER, "--type", "agent"],
    "set-emoji": ["member", "set-emoji", _MEMBER, "x"],
    "update-scopes": ["member", "update-scopes", _MEMBER, "--scopes", "bot:read"],
    "suspend": ["member", "suspend", _MEMBER],
    "reactivate": ["member", "reactivate", _MEMBER],
    "revoke": ["member", "revoke", _MEMBER, "--yes"],
    "rotate-token": ["member", "rotate-token", _MEMBER],
}


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("command", "error", "code", "message"), _MEMBER_COLD_EXITS)
def test_member_cold_path_error(
    mode: str, command: str, error: BaseException, code: str, message: str
) -> None:
    service = MagicMock()
    setattr(service, _COLD_METHOD[command], AsyncMock(side_effect=error))
    result = _invoke(
        ["--format", mode, *_COLD_ARGS[command]],
        patch(_ACTIVE, return_value=False),
        _send(AssertionError("IPC 금지")),
        _service_cm(_MEMBER_CM, service),
    )
    _assert_coded(mode, result, code, message)


@pytest.mark.parametrize("mode", _MODES)
def test_member_info_not_found(mode: str) -> None:
    service = MagicMock()
    service.get = AsyncMock(return_value=None)
    result = _invoke(
        ["--format", mode, "member", "info", _MEMBER],
        _service_cm(_MEMBER_CM, service),
    )
    _assert_coded(mode, result, "MEMBER_NOT_FOUND", _NOT_FOUND)


@pytest.mark.parametrize("mode", _MODES)
def test_member_revoke_requires_confirmation(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "member", "revoke", _MEMBER],
        patch(_ACTIVE, side_effect=AssertionError("판정에 닿으면 안 된다")),
        _send(AssertionError("IPC 금지")),
    )
    message = (
        "위험 명령입니다. --yes를 명시해야 멤버를 폐기합니다."
        " 이 작업은 되돌릴 수 없습니다."
    )
    _assert_coded(mode, result, "CLI_CONFIRMATION_REQUIRED", message)


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["account", "suspend", "acct-1"], id="suspend"),
        pytest.param(
            ["account", "suspend", "acct-1", "--reason", "점검"], id="suspend-reason"
        ),
        pytest.param(["account", "activate", "acct-1"], id="activate"),
    ],
)
def test_account_ipc_failure_without_a_message_json(args: list[str]) -> None:
    result = _invoke(["--format", "json", *args], _send(RuntimeError()))
    _assert_exit("json", result, "EXECUTION_ERROR", "", "")


@pytest.mark.parametrize(
    ("args", "method", "message"),
    [
        pytest.param(
            ["member", "register", "--id", "dup-text", "--type", "agent"],
            "register",
            "이미 존재하는 member_id: dup-text",
            id="register",
        ),
        pytest.param(
            ["member", "suspend", "ghost-text"],
            "suspend",
            "존재하지 않는 멤버: ghost-text",
            id="suspend",
        ),
    ],
)
def test_member_value_error_json(args: list[str], method: str, message: str) -> None:
    service = MagicMock()
    setattr(service, method, AsyncMock(side_effect=ValueError(message)))
    result = _invoke(
        ["--format", "json", *args],
        patch(_ACTIVE, return_value=False),
        _service_cm(_MEMBER_CM, service),
    )
    _assert_exit("json", result, "EXECUTION_ERROR", message, "")
