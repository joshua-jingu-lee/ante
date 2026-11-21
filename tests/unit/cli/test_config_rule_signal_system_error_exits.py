"""``config``·``rule``·``signal``·``system``·``init``·``update`` 명령과
``instrument sync``의 실패 경로 특성 테스트 (#2664 PR ③).

출구마다 JSON·text 두 모드를 지난다. 기대값은 리터럴이다. JSON은 stdout 전체를
사전으로, text는 stdout·stderr의 줄 전체를 비교한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.account.errors import AccountNotFoundError
from ante.cli.main import cli
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.member.models import Member, MemberRole, MemberType
from ante.rule.exceptions import RuleConfigError

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_SERVER_DOWN = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
_FERNET_KEY = "x" * 43 + "="


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(args: list[str], *patches: Any) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args)


def _envelope(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


def _assert_json(
    result: Result,
    envelope: dict[str, str],
    *,
    exit_code: int = 1,
    stderr: str = "",
) -> None:
    assert result.exit_code == exit_code, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == envelope
    assert result.stderr == stderr


def _assert_text(
    result: Result,
    stderr_lines: list[str],
    *,
    exit_code: int = 1,
    stdout_lines: list[str] | None = None,
) -> None:
    assert result.exit_code == exit_code, (result.stdout, result.stderr)
    assert result.stdout.splitlines() == (stdout_lines or [])
    assert result.stderr.splitlines() == stderr_lines


def _failing_cm(error: BaseException) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        raise error
        yield

    return _open


def _yielding_cm(value: Any) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        yield value

    return _open


# ---------------------------------------------------------------- config


def _config_services(*, exists: bool, static_value: Any) -> Any:
    static = MagicMock()
    static.get.return_value = static_value
    dynamic = AsyncMock()
    dynamic.exists = AsyncMock(return_value=exists)
    return patch(
        "ante.cli.commands.config._create_services",
        new=_yielding_cm((static, dynamic, AsyncMock())),
    )


def test_config_get_key_not_found() -> None:
    message = "설정을 찾을 수 없습니다: missing.key"
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "config", "get", "missing.key"],
            _config_services(exists=False, static_value=None),
        )
        if mode == "json":
            _assert_json(result, _envelope("CONFIG_KEY_NOT_FOUND", message))
        else:
            _assert_text(result, [f"Error: CONFIG_KEY_NOT_FOUND: {message}"])


def test_config_get_found_key_is_not_an_error() -> None:
    result = _invoke(
        ["--format", "json", "config", "get", "present.key"],
        _config_services(exists=False, static_value="v"),
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "key": "present.key",
        "value": "v",
        "source": "static",
    }


def _ipc_send(error: BaseException) -> Any:
    return patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(side_effect=error),
    )


def test_config_set_remote_error() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "config", "set", "system.log_level", "DEBUG"],
            _ipc_send(IPCRemoteError("STATIC_CONFIG", "정적 설정입니다")),
        )
        if mode == "json":
            _assert_json(result, _envelope("STATIC_CONFIG", "정적 설정입니다"))
        else:
            _assert_text(result, ["Error: STATIC_CONFIG: 정적 설정입니다"])


def test_config_set_server_not_running() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "config", "set", "custom.key", "v"],
            _ipc_send(IPCServerNotRunningError(_SERVER_DOWN)),
        )
        if mode == "json":
            _assert_json(result, _envelope("IPC_SERVER_NOT_RUNNING", _SERVER_DOWN))
        else:
            _assert_text(result, [f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}"])


def test_config_set_timeout() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "config", "set", "custom.key", "v"],
            _ipc_send(IPCClientTimeoutError("서버 응답 시간 초과")),
        )
        if mode == "json":
            _assert_json(result, _envelope("IPC_TIMEOUT", "서버 응답 시간 초과"))
        else:
            _assert_text(result, ["Error: IPC_TIMEOUT: 서버 응답 시간 초과"])


def test_config_set_unexpected_error() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "config", "set", "custom.key", "v"],
            _ipc_send(RuntimeError("socket broke")),
        )
        if mode == "json":
            _assert_json(result, _envelope("EXECUTION_ERROR", "socket broke"))
        else:
            _assert_text(result, ["Error: EXECUTION_ERROR: socket broke"])


# ---------------------------------------------------------------- rule

_ACCOUNT_MISSING = "계좌 'acc9'를 찾을 수 없습니다."


def _rule_engine(error: BaseException | None = None) -> Any:
    if error is not None:
        return patch(
            "ante.cli.commands.rule._create_rule_engine", new=_failing_cm(error)
        )
    engine = MagicMock()
    engine._global_rules = []
    engine._strategy_rules = {}
    return patch(
        "ante.cli.commands.rule._create_rule_engine",
        new=_yielding_cm((engine, AsyncMock())),
    )


def _no_rule_config() -> Any:
    return patch("ante.cli.commands.rule._load_rules_from_config")


def test_rule_list_account_not_found() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "rule", "list", "--account", "acc9"],
            _rule_engine(AccountNotFoundError(_ACCOUNT_MISSING)),
        )
        if mode == "json":
            _assert_json(result, _envelope("ACCOUNT_NOT_FOUND", _ACCOUNT_MISSING))
        else:
            _assert_text(result, [f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}"])


def test_rule_info_account_not_found() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "rule", "info", "r-7", "--account", "acc9"],
            _rule_engine(AccountNotFoundError(_ACCOUNT_MISSING)),
        )
        if mode == "json":
            _assert_json(result, _envelope("ACCOUNT_NOT_FOUND", _ACCOUNT_MISSING))
        else:
            _assert_text(result, [f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}"])


def test_rule_info_rule_not_found() -> None:
    message = "룰을 찾을 수 없습니다: r-7"
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "rule", "info", "r-7", "--account", "acc9"],
            _rule_engine(),
            _no_rule_config(),
        )
        if mode == "json":
            _assert_json(result, _envelope("RULE_NOT_FOUND", message))
        else:
            _assert_text(result, [f"Error: RULE_NOT_FOUND: {message}"])


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param(
            ["--param", "limit"],
            "잘못된 파라미터 형식: 'limit' (key=value)",
            id="param-without-equals",
        ),
        pytest.param(
            ["--param", "=3"],
            "파라미터 key는 비어 있을 수 없습니다",
            id="param-empty-key",
        ),
        pytest.param(
            ["--params-json", "[1]"],
            "--params-json 값은 JSON object여야 합니다",
            id="params-json-not-object",
        ),
        pytest.param(
            ["--params-json", "{"],
            "--params-json 값은 JSON object여야 합니다",
            id="params-json-invalid",
        ),
    ],
)
def test_rule_update_invalid_params(options: list[str], message: str) -> None:
    for mode in ("json", "text"):
        result = _invoke(
            [
                "--format",
                mode,
                "rule",
                "update",
                "daily_loss_limit",
                "--account",
                "acc9",
                *options,
            ]
        )
        if mode == "json":
            _assert_json(result, _envelope("VALIDATION_ERROR", message))
        else:
            _assert_text(result, [f"Error: VALIDATION_ERROR: {message}"])


def _active_runtime(active: bool) -> Any:
    return patch("ante.cli.cold_path.is_active_runtime", return_value=active)


def _rule_update_args(mode: str) -> list[str]:
    return [
        "--format",
        mode,
        "rule",
        "update",
        "daily_loss_limit",
        "--account",
        "acc9",
        "--param",
        "max_loss_pct=3",
    ]


@pytest.mark.parametrize(
    ("error", "code", "message", "text_line"),
    [
        pytest.param(
            IPCRemoteError("RULE_CONFIG_ERROR", "룰 값이 잘못되었습니다"),
            "RULE_CONFIG_ERROR",
            "룰 값이 잘못되었습니다",
            "Error: RULE_CONFIG_ERROR: 룰 값이 잘못되었습니다",
            id="remote",
        ),
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            f"Error: {_SERVER_DOWN}",
            id="server-not-running",
        ),
        pytest.param(
            IPCClientTimeoutError("서버 응답 시간 초과"),
            "IPC_TIMEOUT",
            "서버 응답 시간 초과",
            "Error: 서버 응답 시간 초과",
            id="timeout",
        ),
        pytest.param(
            click.ClickException("click 실패"),
            "IPC_ERROR",
            "click 실패",
            "Error: click 실패",
            id="plain-click-exception",
        ),
    ],
)
def test_rule_update_ipc_errors(
    error: BaseException, code: str, message: str, text_line: str
) -> None:
    for mode in ("json", "text"):
        result = _invoke(
            _rule_update_args(mode), _active_runtime(True), _ipc_send(error)
        )
        if mode == "json":
            _assert_json(result, _envelope(code, message))
        else:
            _assert_text(result, [text_line])


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            RuntimeError("db 연결 실패"),
            "RULE_UPDATE_ERROR",
            "db 연결 실패",
            id="no-code",
        ),
        pytest.param(
            AccountNotFoundError(_ACCOUNT_MISSING),
            "ACCOUNT_NOT_FOUND",
            _ACCOUNT_MISSING,
            id="account-not-found",
        ),
        pytest.param(
            RuleConfigError("룰 설정 오류"),
            "RULE_CONFIG_ERROR",
            "룰 설정 오류",
            id="rule-config-error",
        ),
    ],
)
def test_rule_update_cold_path_errors(
    error: BaseException, code: str, message: str
) -> None:
    for mode in ("json", "text"):
        result = _invoke(
            _rule_update_args(mode),
            _active_runtime(False),
            patch("ante.cli.commands.rule.open_cli_db", new=_failing_cm(error)),
        )
        if mode == "json":
            _assert_json(result, _envelope(code, message))
        else:
            _assert_text(result, [f"Error: {code}: {message}"])


# ---------------------------------------------------------------- signal


def test_signal_connect_server_down_handshake_passthrough(tmp_path: Path) -> None:
    socket = patch(
        "ante.cli.commands.signal.get_socket_path",
        return_value=str(tmp_path / "missing.sock"),
    )
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "signal", "connect", "--key", "sk_test"], socket
        )
        if mode == "json":
            _assert_json(result, _envelope("IPC_SERVER_NOT_RUNNING", _SERVER_DOWN))
        else:
            assert result.exit_code == 1
            assert result.stdout == ""
            assert result.stderr == _SERVER_DOWN + "\n"


# ---------------------------------------------------------------- system


def _pid(pid: int | None) -> Any:
    return patch("ante.main.read_pid_file", return_value=pid)


def _alive(alive: bool) -> Any:
    return patch("ante.cli.commands.system._is_process_alive", return_value=alive)


def test_system_start_already_running(tmp_path: Path) -> None:
    message = "시스템이 이미 실행 중입니다 (pid=4242)"
    run = patch("ante.cli.commands.system.subprocess.run")
    for mode in ("json", "text"):
        with run as mock_run:
            result = _invoke(
                [
                    "--format",
                    mode,
                    "system",
                    "start",
                    "--config-dir",
                    str(tmp_path),
                ],
                _pid(4242),
                _alive(True),
            )
        mock_run.assert_not_called()
        if mode == "json":
            _assert_json(result, _envelope("ALREADY_RUNNING", message))
        else:
            _assert_text(result, [f"Error: ALREADY_RUNNING: {message}"])


def _static_config() -> Any:
    config = MagicMock()
    config.runtime_pid_path.return_value = Path("/ante-test/run/ante.pid")
    return patch("ante.config.Config.load", return_value=config)


def test_system_stop_pid_not_found() -> None:
    message = "PID 파일이 없습니다 (/ante-test/run/ante.pid)"
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "system", "stop"], _static_config(), _pid(None)
        )
        if mode == "json":
            _assert_json(result, _envelope("PID_NOT_FOUND", message))
        else:
            _assert_text(result, [f"Error: PID_NOT_FOUND: {message}"])


def test_system_stop_process_not_found() -> None:
    message = "프로세스가 존재하지 않습니다 (pid=4242). PID 파일을 정리했습니다."
    for mode in ("json", "text"):
        remove = patch("ante.main._remove_pid_file")
        with remove as mock_remove:
            result = _invoke(
                ["--format", mode, "system", "stop"],
                _static_config(),
                _pid(4242),
                _alive(False),
            )
        mock_remove.assert_called_once()
        if mode == "json":
            _assert_json(result, _envelope("PROCESS_NOT_FOUND", message))
        else:
            _assert_text(result, [f"Error: PROCESS_NOT_FOUND: {message}"])


# ---------------------------------------------------------------- init


@pytest.fixture
def init_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return tmp_path / "cfg"


def _init_state(master: bool, test_account: str) -> list[Any]:
    return [
        patch(
            "ante.cli.commands.init._master_exists_in_db",
            new=AsyncMock(return_value=master),
        ),
        patch(
            "ante.cli.commands.init._test_account_state",
            new=AsyncMock(return_value=test_account),
        ),
    ]


def _make_db(config_dir: Path) -> None:
    (config_dir / "db").mkdir(parents=True, exist_ok=True)
    (config_dir / "db" / "ante.db").write_bytes(b"")


def test_init_test_account_inactive(init_dir: Path) -> None:
    _make_db(init_dir)
    message = (
        "default test account(account_id='test')가 비활성 상태입니다. "
        "`ante account activate test`로 활성화하거나 해당 row를 정리한 "
        "뒤 재시도하세요."
    )
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "init", "--dir", str(init_dir)],
            *_init_state(True, "inactive"),
        )
        if mode == "json":
            _assert_json(result, _envelope("ACCOUNT_TEST_INACTIVE", message))
        else:
            _assert_text(result, [f"Error: ACCOUNT_TEST_INACTIVE: {message}"])
    assert sorted(p.name for p in init_dir.iterdir()) == ["db"]


def test_init_already_initialized(init_dir: Path) -> None:
    _make_db(init_dir)
    (init_dir / "system.toml").write_text("", encoding="utf-8")
    (init_dir / "secrets.env").write_text("", encoding="utf-8")
    message = (
        f"init이 이미 완료된 상태입니다: {init_dir}\n"
        "  재설치를 원하면 디렉토리를 삭제한 뒤 다시 실행하세요."
    )
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "init", "--dir", str(init_dir)],
            *_init_state(True, "active"),
        )
        if mode == "json":
            _assert_json(result, _envelope("CLI_ALREADY_INITIALIZED", message))
        else:
            _assert_text(
                result,
                [
                    f"Error: CLI_ALREADY_INITIALIZED: {message.splitlines()[0]}",
                    message.splitlines()[1],
                ],
            )


def test_init_master_bootstrap_failed(init_dir: Path) -> None:
    message = "master가 이미 존재합니다"
    bootstrap = patch(
        "ante.cli.commands.init._bootstrap_master",
        new=AsyncMock(side_effect=ValueError(message)),
    )
    password = patch("ante.cli.commands.init.generate_password", return_value="pw")
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "init", "--dir", str(init_dir)], bootstrap, password
        )
        if mode == "json":
            _assert_json(result, _envelope("ACCOUNT_MASTER_BOOTSTRAP_FAILED", message))
        else:
            _assert_text(result, [f"Error: ACCOUNT_MASTER_BOOTSTRAP_FAILED: {message}"])


def test_init_test_account_create_failed_without_new_master(init_dir: Path) -> None:
    _make_db(init_dir)
    message = "테스트 계좌 생성 실패: disk full"
    create = patch(
        "ante.cli.commands.init._create_test_account",
        new=AsyncMock(side_effect=RuntimeError("disk full")),
    )
    for mode in ("json", "text"):
        result = _invoke(
            ["--format", mode, "init", "--dir", str(init_dir)],
            *_init_state(True, "missing"),
            create,
        )
        if mode == "json":
            _assert_json(result, _envelope("ACCOUNT_TEST_CREATE_FAILED", message))
        else:
            _assert_text(result, [f"Error: ACCOUNT_TEST_CREATE_FAILED: {message}"])


def test_init_test_account_create_failed_after_new_master(init_dir: Path) -> None:
    message = (
        "테스트 계좌 생성 실패: disk full. "
        "master는 위에 출력된 비밀값으로 접근 가능. "
        "원인 해결 후 재실행 시 test account만 생성됨."
    )
    master = {"member_id": "owner", "name": "Owner", "role": "master", "emoji": "x"}
    patches = [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(return_value=(master, "tok", "rk")),
        ),
        patch("ante.cli.commands.init.generate_password", return_value="pw"),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=RuntimeError("disk full")),
        ),
    ]
    results = {}
    for mode in ("json", "text"):
        results[mode] = _invoke(
            ["--format", mode, "init", "--dir", str(init_dir)], *patches
        )
    json_result = results["json"]
    assert json_result.exit_code == 1, json_result.stderr
    assert json.loads(json_result.stdout) == _envelope(
        "ACCOUNT_TEST_CREATE_FAILED", message
    )
    credentials = json.loads(json_result.stderr)
    assert credentials["token"] == "tok"
    assert credentials["password"] == "pw"
    text_result = results["text"]
    assert text_result.exit_code == 1
    assert text_result.stderr.splitlines()[-1] == (
        f"Error: ACCOUNT_TEST_CREATE_FAILED: {message}"
    )
    assert "tok" in text_result.stdout + text_result.stderr


# ---------------------------------------------------------------- update

_DB_PATH = "/ante-test/db/ante.db"


def _versions(latest: str | None) -> list[Any]:
    return [
        patch("ante.update.checker.get_current_version", return_value="0.6.1"),
        patch("ante.update.checker.get_latest_version", return_value=latest),
    ]


def _server_running(running: bool) -> Any:
    return patch("ante.cli.commands.update.check_server_running", return_value=running)


def _paths() -> list[Any]:
    return [
        patch("ante.cli.main.get_db_path", return_value=_DB_PATH),
        patch("ante.cli.main.get_data_path", return_value="/ante-test/data"),
    ]


def _disk(ok: bool, msg: str = "") -> Any:
    return patch("ante.cli.commands.update.check_disk_space", return_value=(ok, msg))


def _executor(
    *, upgrade: bool = True, migrate: bool = True, rollback: bool = True
) -> list[Any]:
    return [
        patch("ante.db.backup.backup_db"),
        patch(
            "ante.update.executor.snapshot_dependencies",
            return_value=Path("/ante-test/db/snap.txt"),
        ),
        patch("ante.update.executor.pip_upgrade", return_value=upgrade),
        patch("ante.update.executor.run_post_update_migrations", return_value=migrate),
        patch("ante.update.executor.rollback_update", return_value=rollback),
    ]


def test_update_check_failed_on_check() -> None:
    for mode in ("json", "text"):
        result = _invoke(["update", "--check", "--format", mode], *_versions(None))
        if mode == "json":
            _assert_json(
                result, _envelope("UPDATE_CHECK_FAILED", "PyPI 버전 확인 실패")
            )
        else:
            _assert_text(
                result,
                ["Error: UPDATE_CHECK_FAILED: PyPI 버전 확인 실패"],
                stdout_lines=["현재 버전: 0.6.1"],
            )


def test_update_confirmation_required() -> None:
    message = (
        "업데이트 실행에는 --yes가 필요합니다 (현재 0.6.1). 재실행: ante update --yes"
    )
    for mode in ("json", "text"):
        result = _invoke(["update", "--format", mode], *_versions("0.7.0"))
        if mode == "json":
            _assert_json(result, _envelope("CLI_CONFIRMATION_REQUIRED", message))
        else:
            _assert_text(result, [f"Error: CLI_CONFIRMATION_REQUIRED: {message}"])


def test_update_server_running() -> None:
    message = "서버가 실행 중입니다. 먼저 서버를 중지하거나 --force 옵션을 사용하세요."
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions("0.7.0"),
            _server_running(True),
        )
        if mode == "json":
            _assert_json(result, _envelope("UPDATE_SERVER_RUNNING", message))
        else:
            _assert_text(result, [f"Error: UPDATE_SERVER_RUNNING: {message}"])


def test_update_check_failed_on_update() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions(None),
            _server_running(False),
        )
        if mode == "json":
            _assert_json(
                result, _envelope("UPDATE_CHECK_FAILED", "PyPI 버전 확인 실패")
            )
        else:
            _assert_text(
                result,
                ["Error: UPDATE_CHECK_FAILED: PyPI 버전 확인 실패"],
                stdout_lines=["현재 버전: 0.6.1"],
            )


_DISK_MESSAGE = (
    "디스크 공간 부족: 필요 300MB, 여유 12MB. "
    "불필요한 파일을 정리한 후 다시 시도하세요."
)


def test_update_insufficient_disk_space() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions("0.7.0"),
            _server_running(False),
            *_paths(),
            _disk(False, _DISK_MESSAGE),
            *_executor(),
        )
        if mode == "json":
            _assert_json(
                result, _envelope("UPDATE_INSUFFICIENT_DISK_SPACE", _DISK_MESSAGE)
            )
        else:
            _assert_text(
                result,
                [f"Error: UPDATE_INSUFFICIENT_DISK_SPACE: {_DISK_MESSAGE}"],
                stdout_lines=["현재 버전: 0.6.1"],
            )


_PROGRESS = [
    "현재 버전: 0.6.1",
    "의존성 스냅샷 저장 중...",
    "스냅샷 저장 완료: /ante-test/db/snap.txt",
    "업데이트 중: 0.6.1 → 0.7.0...",
]


def test_update_install_failed() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions("0.7.0"),
            _server_running(False),
            *_paths(),
            _disk(True),
            *_executor(upgrade=False),
        )
        if mode == "json":
            _assert_json(result, _envelope("UPDATE_INSTALL_FAILED", "업데이트 실패"))
        else:
            _assert_text(
                result,
                ["Error: UPDATE_INSTALL_FAILED: 업데이트 실패"],
                stdout_lines=_PROGRESS,
            )


def test_update_migration_failed_rollback_done() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions("0.7.0"),
            _server_running(False),
            *_paths(),
            _disk(True),
            *_executor(migrate=False, rollback=True),
        )
        if mode == "json":
            _assert_json(
                result,
                _envelope("UPDATE_MIGRATION_FAILED", "마이그레이션 실패. 롤백 완료."),
            )
        else:
            _assert_text(
                result,
                [
                    "마이그레이션 실패. 자동 롤백 시도 중...",
                    "Error: UPDATE_MIGRATION_FAILED: 마이그레이션 실패. 롤백 완료.",
                ],
                stdout_lines=[
                    *_PROGRESS,
                    "DB 마이그레이션 실행 중...",
                    "롤백 완료: 0.6.1으로 복원됨",
                    "의존성 복원: pip install -r /ante-test/db/snap.txt",
                ],
            )


def test_update_migration_failed_rollback_failed() -> None:
    for mode in ("json", "text"):
        result = _invoke(
            ["update", "--yes", "--format", mode],
            *_versions("0.7.0"),
            _server_running(False),
            *_paths(),
            _disk(True),
            *_executor(migrate=False, rollback=False),
        )
        if mode == "json":
            _assert_json(
                result,
                _envelope(
                    "UPDATE_ROLLBACK_FAILED", "마이그레이션 실패. 자동 롤백 실패."
                ),
            )
        else:
            _assert_text(
                result,
                [
                    "마이그레이션 실패. 자동 롤백 시도 중...",
                    "자동 롤백 실패. 수동 복구 필요:",
                    "  pip install ante==0.6.1",
                    "  pip install -r /ante-test/db/snap.txt",
                    f"  cp {_DB_PATH}.bak.v0.6.1 {_DB_PATH}",
                    "Error: UPDATE_ROLLBACK_FAILED: 마이그레이션 실패. 자동 롤백 실패.",
                ],
                stdout_lines=[*_PROGRESS, "DB 마이그레이션 실행 중..."],
            )


# ---------------------------------------------------------------- instrument sync


def _sync_config(broker: dict[str, Any]) -> Any:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: (
        broker if key == "broker" else default
    )
    return patch("ante.config.Config.load", return_value=config)


def test_instrument_sync_without_broker_config(tmp_path: Path) -> None:
    for mode in ("json", "text"):
        result = _invoke(
            [
                "--format",
                mode,
                "instrument",
                "sync",
                "--db-path",
                str(tmp_path / "i.db"),
            ],
            _sync_config({}),
        )
        if mode == "json":
            _assert_json(
                result, _envelope("INSTRUMENT_SYNC_FAILED", "브로커 설정이 없습니다.")
            )
        else:
            _assert_text(
                result, ["Error: INSTRUMENT_SYNC_FAILED: 브로커 설정이 없습니다."]
            )


def test_instrument_sync_empty_result(tmp_path: Path) -> None:
    db = AsyncMock()
    db.fetch_all = AsyncMock(return_value=[])
    adapter = MagicMock()
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    adapter.get_instruments = AsyncMock(return_value=[])
    service = MagicMock()
    service.return_value.initialize = AsyncMock()
    patches = [
        _sync_config({"app_key": "k"}),
        patch("ante.cli.commands.instrument.open_cli_db", new=_yielding_cm(db)),
        patch("ante.broker.kis.KISAdapter", return_value=adapter),
        patch("ante.instrument.service.InstrumentService", new=service),
    ]
    for mode in ("json", "text"):
        result = _invoke(
            [
                "--format",
                mode,
                "instrument",
                "sync",
                "--db-path",
                str(tmp_path / "i.db"),
            ],
            *patches,
        )
        if mode == "json":
            _assert_json(
                result,
                _envelope(
                    "INSTRUMENT_SYNC_FAILED", "종목 데이터를 가져오지 못했습니다."
                ),
            )
        else:
            _assert_text(
                result,
                ["Error: INSTRUMENT_SYNC_FAILED: 종목 데이터를 가져오지 못했습니다."],
            )
    adapter.disconnect.assert_awaited()
