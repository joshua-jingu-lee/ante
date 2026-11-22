"""CLI 진입점의 단일 에러 출구 (#2641, #2571, #2631).

명령 밖으로 나온 처리되지 않은 ``Exception``은 ``AuthenticatedGroup.main``의
훅이 받아 다음 형식으로 끝낸다(``docs/specs/contracts/error-taxonomy.md``).

- JSON 모드: stdout에 ``{"status": "error", "code": <코드>, "message": <메시지>}``.
- text 모드: stderr에 ``Error: <code>: <message>`` 한 줄.
- 종료 코드: 에러 레지스트리의 ``ErrorSpec.exit_code``(0이면 1).

``BaseException`` 계열(``SystemExit``, ``KeyboardInterrupt``,
``asyncio.CancelledError``)과 Click 자신의 예외 분기는 훅의 대상이 아니다.

기대값은 계약의 리터럴로 적는다. 구현 모듈의 상수를 기대값으로 쓰지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.contracts.cli_errors import CliMissingRequiredInputError
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


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(
    args: list[str],
    *,
    patches: tuple[Any, ...] = (),
    auth: Callable[[click.Context], None] | None = _set_master,
    **kwargs: Any,
) -> Result:
    """인증을 대역으로 바꾸고 stdout·stderr를 나눠 받는다."""
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        if auth is not None:
            stack.enter_context(
                patch("ante.cli.main.authenticate_member", side_effect=auth)
            )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args, **kwargs)


def _envelope(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


def _assert_json_exit(
    result: Result, code: str, message: str, exit_code: int = 1
) -> None:
    """JSON 모드: stdout 전체가 봉투 하나, stderr는 비어 있고, 예외가 새지 않는다."""
    assert result.exit_code == exit_code, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == _envelope(code, message)
    assert result.stderr == ""
    assert isinstance(result.exception, SystemExit), repr(result.exception)


def _assert_text_exit(result: Result, line: str, exit_code: int = 1) -> None:
    """text 모드: stdout은 비고, stderr는 한 줄뿐이다."""
    assert result.exit_code == exit_code, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.splitlines() == [line]
    assert isinstance(result.exception, SystemExit), repr(result.exception)


# ── 잎 명령 하나에 예외를 주입하는 도구 ────────────────────────────────────


def _walk_leaves(
    group: click.Group, prefix: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], click.Command]]:
    for name, sub in group.commands.items():
        path = (*prefix, name)
        if isinstance(sub, click.Group):
            yield from _walk_leaves(sub, path)
        else:
            yield path, sub


def _leaf(path: tuple[str, ...]) -> click.Command:
    return dict(_walk_leaves(cli))[path]


def _raising(exc: BaseException) -> Callable[..., None]:
    def _callback(*args: object, **kwargs: object) -> None:
        raise exc

    return _callback


@pytest.fixture
def inject(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[tuple[str, ...], BaseException], None]:
    """잎 명령의 인자를 비우고 콜백을 ``exc``를 던지는 것으로 바꾼다."""

    def _inject(path: tuple[str, ...], exc: BaseException) -> None:
        cmd = _leaf(path)
        monkeypatch.setattr(cmd, "params", [])
        monkeypatch.setattr(cmd, "callback", _raising(exc))

    return _inject


class _UnclassifiedError(Exception):
    """레지스트리에 없는 예외."""


# ── 훅의 경계 ──────────────────────────────────────────────────────────────


class TestHookCatchesUnhandledException:
    def test_json_mode_emits_execution_error_envelope(self, inject) -> None:
        inject(("bot", "list"), _UnclassifiedError("boom"))
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "EXECUTION_ERROR", "boom")

    def test_text_mode_emits_one_line_on_stderr(self, inject) -> None:
        inject(("bot", "list"), _UnclassifiedError("boom"))
        result = _invoke(["--format", "text", "bot", "list"])
        _assert_text_exit(result, "Error: EXECUTION_ERROR: boom")

    def test_default_format_is_text(self, inject) -> None:
        inject(("bot", "list"), _UnclassifiedError("boom"))
        result = _invoke(["bot", "list"])
        _assert_text_exit(result, "Error: EXECUTION_ERROR: boom")

    def test_empty_message_keeps_the_shape(self, inject) -> None:
        inject(("bot", "list"), KeyError())
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "EXECUTION_ERROR", "")

    @pytest.mark.parametrize(
        ("exc", "code", "message"),
        [
            pytest.param(
                "ante.bot.exceptions:BotNotFoundError",
                "BOT_NOT_FOUND",
                "Bot not found: bot-x",
                id="bot-not-found",
            ),
            pytest.param(
                "ante.account.errors:AccountNotFoundError",
                "ACCOUNT_NOT_FOUND",
                "계좌 없음",
                id="account-not-found",
            ),
            pytest.param(
                "ante.treasury.exceptions:TreasuryNotConfiguredError",
                "TREASURY_NOT_CONFIGURED",
                "자금 관리 없음",
                id="treasury-not-configured",
            ),
        ],
    )
    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_registered_exception_uses_registry_code(
        self, inject, exc: str, code: str, message: str, mode: str
    ) -> None:
        module, _, name = exc.partition(":")
        cls = getattr(__import__(module, fromlist=[name]), name)
        arg = "bot-x" if name == "BotNotFoundError" else message
        inject(("bot", "list"), cls(arg))
        result = _invoke(["--format", mode, "bot", "list"])
        if mode == "json":
            _assert_json_exit(result, code, message)
        else:
            _assert_text_exit(result, f"Error: {code}: {message}")

    def test_code_attribute_outside_registry_is_used(self, inject) -> None:
        class _CodedError(Exception):
            code = "SOME_DOMAIN_CODE"

        inject(("bot", "list"), _CodedError("coded"))
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "SOME_DOMAIN_CODE", "coded")

    def test_integer_code_attribute_becomes_execution_error(self, inject) -> None:
        class _HttpLikeError(Exception):
            code = 500

        inject(("bot", "list"), _HttpLikeError("server said no"))
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "EXECUTION_ERROR", "server said no")


_IDEMPOTENT_CASES = [
    pytest.param(
        "CLI_MISSING_REQUIRED_INPUT: m",
        "Error: CLI_MISSING_REQUIRED_INPUT: m\n",
        id="same-code-prefix",
    ),
    pytest.param(
        "CLI_MISSING_REQUIRED_INPUT: ",
        "Error: CLI_MISSING_REQUIRED_INPUT: \n",
        id="message-is-exactly-the-prefix",
    ),
    pytest.param(
        "CLI_CONFIRMATION_REQUIRED: m",
        "Error: CLI_MISSING_REQUIRED_INPUT: CLI_CONFIRMATION_REQUIRED: m\n",
        id="other-code-prefix",
    ),
    pytest.param(
        "CLI_MISSING_REQUIRED_INPUT:m",
        "Error: CLI_MISSING_REQUIRED_INPUT: CLI_MISSING_REQUIRED_INPUT:m\n",
        id="colon-without-space",
    ),
    pytest.param(
        "cli_missing_required_input: m",
        "Error: CLI_MISSING_REQUIRED_INPUT: cli_missing_required_input: m\n",
        id="lowercase-code",
    ),
    pytest.param(
        " CLI_MISSING_REQUIRED_INPUT: m",
        "Error: CLI_MISSING_REQUIRED_INPUT:  CLI_MISSING_REQUIRED_INPUT: m\n",
        id="leading-space",
    ),
    pytest.param(
        "m",
        "Error: CLI_MISSING_REQUIRED_INPUT: m\n",
        id="no-prefix",
    ),
    pytest.param(
        "",
        "Error: CLI_MISSING_REQUIRED_INPUT: \n",
        id="empty-message",
    ),
]


class TestHookIdempotentPrefix:
    """text 줄의 멱등 접두 (#2738).

    메시지가 이미 ``<code>: ``로 시작하면 접두를 다시 붙이지 않는다.
    """

    def test_cases_are_present(self) -> None:
        assert len(_IDEMPOTENT_CASES) == 8

    @pytest.mark.parametrize(("message", "stderr"), _IDEMPOTENT_CASES)
    def test_text_line(self, inject, message: str, stderr: str) -> None:
        inject(("bot", "list"), CliMissingRequiredInputError(message))
        result = _invoke(["--format", "text", "bot", "list"])
        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stdout == ""
        assert result.stderr == stderr
        assert isinstance(result.exception, SystemExit), repr(result.exception)

    @pytest.mark.parametrize(("message", "stderr"), _IDEMPOTENT_CASES)
    def test_json_message_is_not_normalized(
        self, inject, message: str, stderr: str
    ) -> None:
        inject(("bot", "list"), CliMissingRequiredInputError(message))
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "CLI_MISSING_REQUIRED_INPUT", message)


class TestHookExitCodeFromRegistry:
    """종료 코드는 ``ErrorSpec.exit_code``를 읽는다. 0이면 1이다."""

    @pytest.mark.parametrize(
        ("spec_exit", "expected_exit"),
        [(3, 3), (7, 7), (1, 1), (0, 1)],
    )
    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_exit_code(
        self,
        inject,
        monkeypatch: pytest.MonkeyPatch,
        spec_exit: int,
        expected_exit: int,
        mode: str,
    ) -> None:
        from ante.contracts.error_registry import EXCEPTION_TO_SPEC
        from ante.contracts.errors import ErrorSpec

        monkeypatch.setitem(
            EXCEPTION_TO_SPEC,
            _UnclassifiedError,
            ErrorSpec(code="TEST_EXIT_CODE", category="internal", exit_code=spec_exit),
        )
        inject(("bot", "list"), _UnclassifiedError("custom"))
        result = _invoke(["--format", mode, "bot", "list"])
        if mode == "json":
            _assert_json_exit(result, "TEST_EXIT_CODE", "custom", expected_exit)
        else:
            _assert_text_exit(result, "Error: TEST_EXIT_CODE: custom", expected_exit)


class TestHookLeavesOtherExitsAlone:
    """훅 바로 밖: BaseException 계열과 Click 자신의 출구."""

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_system_exit_passes_through(self, inject, mode: str) -> None:
        inject(("bot", "list"), SystemExit(4))
        result = _invoke(["--format", mode, "bot", "list"])
        assert result.exit_code == 4
        assert (result.stdout, result.stderr) == ("", "")

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_click_exit_passes_through(self, inject, mode: str) -> None:
        inject(("bot", "list"), click.exceptions.Exit(5))
        result = _invoke(["--format", mode, "bot", "list"])
        assert result.exit_code == 5
        assert (result.stdout, result.stderr) == ("", "")

    @pytest.mark.parametrize("mode", ["json", "text"])
    @pytest.mark.parametrize(
        ("exc", "stderr_lines"),
        [
            pytest.param(
                KeyboardInterrupt(), ["", "Aborted!"], id="keyboard-interrupt"
            ),
            pytest.param(EOFError(), ["", "Aborted!"], id="eof"),
            pytest.param(click.Abort(), ["Aborted!"], id="abort"),
        ],
    )
    def test_abort_family_prints_aborted(
        self, inject, mode: str, exc: BaseException, stderr_lines: list[str]
    ) -> None:
        """Click은 ``KeyboardInterrupt``·``EOFError``를 빈 줄과 ``Abort``로 바꾼다."""
        inject(("bot", "list"), exc)
        result = _invoke(["--format", mode, "bot", "list"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.splitlines() == stderr_lines

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_cancelled_error_escapes(self, inject, mode: str) -> None:
        inject(("bot", "list"), asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            _invoke(["--format", mode, "bot", "list"])

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_standalone_false_reraises(self, inject, mode: str) -> None:
        exc = _UnclassifiedError("raw")
        inject(("bot", "list"), exc)
        result = _invoke(["--format", mode, "bot", "list"], standalone_mode=False)
        assert result.exception is exc
        assert (result.stdout, result.stderr) == ("", "")

    def test_standalone_false_text_click_exception_reraises(self, inject) -> None:
        """text 모드의 ``standalone_mode=False``는 Click 예외도 그대로 올린다."""
        exc = click.ClickException("plain")
        inject(("bot", "list"), exc)
        result = _invoke(["--format", "text", "bot", "list"], standalone_mode=False)
        assert result.exception is exc
        assert (result.stdout, result.stderr) == ("", "")

    def test_text_usage_error_keeps_click_default(self) -> None:
        result = _invoke(["--format", "text", "bot", "list", "--no-such-flag"])
        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr.splitlines()[0].startswith("Usage: ")
        assert result.stderr.splitlines()[-1] == "Error: No such option: --no-such-flag"

    def test_json_usage_error_keeps_envelope(self) -> None:
        result = _invoke(["--format", "json", "bot", "list", "--no-such-flag"])
        _assert_json_exit(result, "CLI_USAGE_ERROR", "No such option: --no-such-flag")

    def test_json_click_exception_reads_ipc_attribute(self, inject) -> None:
        """속성만 붙인 ``ClickException`` 대역: 기존 분기가 속성으로 코드를 읽는다."""
        exc = click.ClickException("IGNORED: wrapped")
        exc.ipc_error_code = "BOT_NOT_RUNNING"  # type: ignore[attr-defined]
        exc.ipc_error_message = "봇이 실행 중이 아닙니다"  # type: ignore[attr-defined]
        inject(("bot", "list"), exc)
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "BOT_NOT_RUNNING", "봇이 실행 중이 아닙니다")

    def test_json_click_exception_without_attribute_is_ipc_error(self, inject) -> None:
        inject(("bot", "list"), click.ClickException("plain"))
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, "IPC_ERROR", "plain")

    def test_text_click_exception_keeps_click_default(self, inject) -> None:
        inject(("bot", "list"), click.ClickException("plain"))
        result = _invoke(["--format", "text", "bot", "list"])
        _assert_text_exit(result, "Error: plain")


class TestAuthStageException:
    """인증 단계에서 난 예외도 같은 출구로 끝난다(#2631의 모양)."""

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_authenticate_member_raises(self, mode: str) -> None:
        def _boom(ctx: click.Context) -> None:
            raise sqlite3.OperationalError("auth db broke")

        result = _invoke(["--format", mode, "bot", "list"], auth=_boom)
        if mode == "json":
            _assert_json_exit(result, "EXECUTION_ERROR", "auth db broke")
        else:
            _assert_text_exit(result, "Error: EXECUTION_ERROR: auth db broke")


# ── #2631: 실제 인증 경로의 DB 오류 ────────────────────────────────────────


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "cfg"
    (cfg / "db").mkdir(parents=True)
    (cfg / "system.toml").write_text("", encoding="utf-8")
    (cfg / "secrets.env").write_text("", encoding="utf-8")
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ANTE_MEMBER_TOKEN", "ante_ak_fake")
    return cfg


def _drift_db(cfg: Path) -> None:
    """``connect()``는 되고 ``initialize()``의 DDL이 실패하는 DB."""
    con = sqlite3.connect(cfg / "db" / "ante.db")
    try:
        con.execute("CREATE TABLE members (member_id TEXT)")
        con.commit()
    finally:
        con.close()


class TestIssue2631AuthDbErrors:
    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_initialize_ddl_failure(self, config_dir: Path, mode: str) -> None:
        _drift_db(config_dir)
        result = _invoke(["--format", mode, "member", "list"], auth=None)
        if mode == "json":
            _assert_json_exit(result, "EXECUTION_ERROR", "no such column: type")
        else:
            _assert_text_exit(result, "Error: EXECUTION_ERROR: no such column: type")

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_authenticate_query_failure(self, config_dir: Path, mode: str) -> None:
        failing = AsyncMock(side_effect=sqlite3.OperationalError("database is locked"))
        result = _invoke(
            ["--format", mode, "member", "list"],
            auth=None,
            patches=(patch("ante.member.service.MemberService.authenticate", failing),),
        )
        failing.assert_awaited_once_with("ante_ak_fake")
        if mode == "json":
            _assert_json_exit(result, "EXECUTION_ERROR", "database is locked")
        else:
            _assert_text_exit(result, "Error: EXECUTION_ERROR: database is locked")

    def test_control_corrupt_db_file_is_auth_failed(self, config_dir: Path) -> None:
        db = config_dir / "db" / "ante.db"
        db.write_bytes(b"not a sqlite database" * 100)
        result = _invoke(["--format", "json", "member", "list"], auth=None)
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload == _envelope(
            "auth_failed",
            f"인증 실패: DB 접근 불가 ({db}): file is not a database. "
            "`ante init --dir <config_dir>` 이후 동일 `--config-dir`로 실행하세요.",
        )

    def test_control_wrong_token_is_auth_failed(self, config_dir: Path) -> None:
        result = _invoke(["--format", "json", "member", "list"], auth=None)
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "auth_failed"
        assert payload["message"].startswith("인증 실패: ")
        assert set(payload) == {"status", "code", "message"}


# ── #2571: 세 명령의 DB 오류 ──────────────────────────────────────────────


def _db_cm(db: MagicMock) -> Callable[..., Any]:
    @asynccontextmanager
    async def _cm(ctx: click.Context) -> Any:
        yield db

    return _cm


def _failing_db(**methods: BaseException) -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    for name, exc in methods.items():
        setattr(db, name, AsyncMock(side_effect=exc))
    return db


def _expect(result: Result, mode: str, message: str) -> None:
    if mode == "json":
        _assert_json_exit(result, "EXECUTION_ERROR", message)
    else:
        _assert_text_exit(result, f"Error: EXECUTION_ERROR: {message}")


@pytest.mark.parametrize("mode", ["json", "text"])
class TestIssue2571:
    def test_bot_positions_offline_db_error(self, mode: str) -> None:
        from ante.contracts.ipc_client_errors import IPCServerNotRunningError

        db = _failing_db(fetch_one=sqlite3.OperationalError("database is locked"))
        result = _invoke(
            ["--format", mode, "bot", "positions", "bot-db"],
            patches=(
                patch(
                    "ante.cli.commands.ipc_helpers.ipc_send",
                    new=AsyncMock(
                        side_effect=IPCServerNotRunningError(
                            "서버가 실행 중이 아닙니다."
                        )
                    ),
                ),
                patch("ante.cli.commands.bot.open_cli_db", new=_db_cm(db)),
            ),
        )
        db.fetch_one.assert_awaited_once()
        _expect(result, mode, "database is locked")

    @pytest.mark.parametrize("argv", [["rule", "list"], ["rule", "info", "r-1"]])
    def test_rule_account_lookup_db_error(self, mode: str, argv: list[str]) -> None:
        db = _failing_db(fetch_one=sqlite3.OperationalError("no such column: x"))
        result = _invoke(
            ["--format", mode, *argv, "--account", "acc-1"],
            patches=(patch("ante.cli.commands.rule.open_cli_db", new=_db_cm(db)),),
        )
        db.fetch_one.assert_awaited_once()
        _expect(result, mode, "no such column: x")

    def test_rule_no_such_table_is_still_account_not_found(self, mode: str) -> None:
        """대조군: 「no such table」 정규화는 그대로다."""
        db = _failing_db(fetch_one=sqlite3.OperationalError("no such table: accounts"))
        result = _invoke(
            ["--format", mode, "rule", "list", "--account", "acc-1"],
            patches=(patch("ante.cli.commands.rule.open_cli_db", new=_db_cm(db)),),
        )
        message = "계좌 'acc-1'를 찾을 수 없습니다."
        if mode == "json":
            _assert_json_exit(result, "ACCOUNT_NOT_FOUND", message)
        else:
            _assert_text_exit(result, f"Error: ACCOUNT_NOT_FOUND: {message}")

    def test_audit_list_query_error_closes_db_once(
        self, mode: str, tmp_path: Path
    ) -> None:
        db = MagicMock()
        db.connect = AsyncMock()
        db.close = AsyncMock()
        audit_logger = MagicMock()
        audit_logger.initialize = AsyncMock()
        audit_logger.query = AsyncMock(
            side_effect=sqlite3.OperationalError("disk I/O error")
        )
        result = _invoke(
            ["--config-dir", str(tmp_path), "--format", mode, "audit", "list"],
            patches=(
                patch("ante.core.database.Database", MagicMock(return_value=db)),
                patch("ante.audit.AuditLogger", MagicMock(return_value=audit_logger)),
            ),
        )
        audit_logger.query.assert_awaited_once()
        assert db.close.await_count == 1
        _expect(result, mode, "disk I/O error")


# ── 생성 테스트 1: 모든 잎 명령에 예외 주입 ────────────────────────────────


class _InjectedError(Exception):
    pass


def test_every_leaf_command_ends_in_the_single_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Click 트리의 모든 잎 명령 × 두 모드: 콜백의 예외가 봉투 또는 한 줄로 끝난다."""
    leaves = list(_walk_leaves(cli))
    assert leaves, "Click 잎 명령을 하나도 찾지 못했다(빈 통과 방지)"
    for _, cmd in leaves:
        monkeypatch.setattr(cmd, "params", [])
    failures: list[tuple[str, str, object]] = []
    reached = 0
    for path, cmd in leaves:
        name = " ".join(path)
        monkeypatch.setattr(
            cmd, "callback", _raising(_InjectedError(f"injected {name}"))
        )
        for mode in ("json", "text"):
            result = _invoke(["--format", mode, *path])
            try:
                if mode == "json":
                    _assert_json_exit(result, "EXECUTION_ERROR", f"injected {name}")
                else:
                    _assert_text_exit(
                        result, f"Error: EXECUTION_ERROR: injected {name}"
                    )
                assert "Traceback" not in result.stdout + result.stderr
            except AssertionError as exc:
                failures.append((mode, name, exc))
            else:
                reached += 1
    assert failures == []
    assert reached == 2 * len(leaves)


_SAMPLE_LEAVES = (
    ("bot", "list"),
    ("init",),
    ("member", "reset-password"),
    ("feed", "status"),
    ("audit", "list"),
)


@pytest.mark.parametrize("mode", ["json", "text"])
@pytest.mark.parametrize(
    ("exc", "message"),
    [
        pytest.param(RuntimeError("rt failed"), "rt failed", id="RuntimeError"),
        pytest.param(OSError("os failed"), "os failed", id="OSError"),
        pytest.param(ValueError("bad value"), "bad value", id="ValueError"),
        pytest.param(KeyError("k"), "'k'", id="KeyError"),
    ],
)
def test_builtin_exception_types_on_sample_leaves(
    monkeypatch: pytest.MonkeyPatch, mode: str, exc: Exception, message: str
) -> None:
    """내장 예외 타입 넷 × 고정 표본 잎 다섯: 타입마다 같은 출구로 끝난다."""
    for path in _SAMPLE_LEAVES:
        cmd = _leaf(path)
        monkeypatch.setattr(cmd, "params", [])
        monkeypatch.setattr(cmd, "callback", _raising(exc))
        result = _invoke(["--format", mode, *path])
        if mode == "json":
            _assert_json_exit(result, "EXECUTION_ERROR", message)
        else:
            _assert_text_exit(result, f"Error: EXECUTION_ERROR: {message}")


def test_leaf_walk_matches_cli_contract_registry() -> None:
    """잎 명령 집합 = CLI 계약 레지스트리 + 레지스트리 밖으로 알려진 잎."""
    from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY

    leaves = {path for path, _ in _walk_leaves(cli)}
    registered = set(CLI_COMMAND_REGISTRY)
    assert registered <= leaves
    assert {p for p in leaves - registered if p[0] != "feed"} == {
        ("init",),
        ("update",),
    }


# ── 생성 테스트 2: 레지스트리 항목의 CLI·IPC 코드 일치 ─────────────────────


def _registry_instance(cls: type[BaseException]) -> BaseException:
    """``cls.__new__(cls)``. 그것이 실패하거나 ``str()``할 수 없으면 ``cls("x")``."""
    try:
        exc = cls.__new__(cls)
        str(exc)
    except Exception:
        return cls("x")
    return exc


def _dispatch_raising(exc: BaseException) -> dict:
    """``exc``를 던지는 핸들러 하나를 둔 실제 ``IPCServer._dispatch``의 응답."""
    from ante.ipc.registry import CommandRegistry
    from ante.ipc.server import IPCServer, IPCServerState

    async def _handler(svc: object, args: dict, actor: str) -> dict:
        raise exc

    registry = CommandRegistry()
    registry.register("test.raise", _handler, is_mutating=False)
    server = IPCServer("/nonexistent.sock", MagicMock(), registry)
    server._state = IPCServerState.RUNNING
    return asyncio.run(server._dispatch({"id": "r1", "command": "test.raise"}))


def test_registry_entries_have_same_code_on_cli_and_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ante.contracts.error_registry import EXCEPTION_TO_SPEC

    entries = list(EXCEPTION_TO_SPEC.items())
    assert entries, "EXCEPTION_TO_SPEC가 비어 있다(빈 통과 방지)"
    cmd = _leaf(("bot", "list"))
    monkeypatch.setattr(cmd, "params", [])
    mismatches: list[tuple[str, str, object, str, int]] = []
    checked = 0
    for cls, spec in entries:
        exc = _registry_instance(cls)
        monkeypatch.setattr(cmd, "callback", _raising(exc))
        result = _invoke(["--format", "json", "bot", "list"])
        try:
            cli_code = json.loads(result.stdout)["code"]
        except (json.JSONDecodeError, KeyError, TypeError):
            cli_code = f"<no envelope: {result.exception!r}>"
        ipc_code = _dispatch_raising(exc)["error"]["code"]
        if not (cli_code == ipc_code == spec.code) or result.exit_code != (
            spec.exit_code or 1
        ):
            mismatches.append(
                (cls.__name__, spec.code, cli_code, ipc_code, result.exit_code)
            )
        checked += 1
    assert mismatches == []
    assert checked == len(EXCEPTION_TO_SPEC)


def test_registry_entries_text_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """레지스트리 항목 전부를 text 모드로: stderr 한 줄, stdout 비움, 항목의 exit.

    Click 예외인 항목(IPC 클라이언트 예외)은 text 모드에서 Click 기본 출력
    ``Error: <message>``로 끝난다.
    """
    from ante.contracts.error_registry import EXCEPTION_TO_SPEC

    entries = list(EXCEPTION_TO_SPEC.items())
    assert entries, "EXCEPTION_TO_SPEC가 비어 있다(빈 통과 방지)"
    cmd = _leaf(("bot", "list"))
    monkeypatch.setattr(cmd, "params", [])
    mismatches: list[tuple[str, object, object, object, int]] = []
    checked = 0
    for cls, spec in entries:
        exc = _registry_instance(cls)
        monkeypatch.setattr(cmd, "callback", _raising(exc))
        result = _invoke(["--format", "text", "bot", "list"])
        if isinstance(exc, click.ClickException):
            expected = [f"Error: {exc.message}"]
            expected_exit = exc.exit_code
        else:
            expected = [f"Error: {spec.code}: {exc}"]
            expected_exit = spec.exit_code or 1
        got = (result.stdout, result.stderr.splitlines(), result.exit_code)
        if got != ("", expected, expected_exit):
            mismatches.append((cls.__name__, *got, expected_exit))
        checked += 1
    assert mismatches == []
    assert checked == len(EXCEPTION_TO_SPEC)


# ── IPC 클라이언트의 타입 예외 ────────────────────────────────────────────


class TestIpcSendTypedExceptions:
    def _send(self, monkeypatch: pytest.MonkeyPatch, **send: Any) -> BaseException:
        from ante.cli.commands import ipc_helpers

        monkeypatch.setattr(
            ipc_helpers, "get_socket_path", lambda config_dir=None: "/x.sock"
        )
        monkeypatch.setattr(ipc_helpers.IPCClient, "send", AsyncMock(**send))
        with pytest.raises(click.ClickException) as info:
            asyncio.run(ipc_helpers.ipc_send("bot.list", {}))
        return info.value

    def test_server_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ante.ipc.exceptions import ServerNotRunningError

        exc = self._send(monkeypatch, side_effect=ServerNotRunningError("gone"))
        assert type(exc).__name__ == "IPCServerNotRunningError"
        assert (exc.ipc_error_code, exc.ipc_error_message, exc.message) == (  # type: ignore[attr-defined]
            "IPC_SERVER_NOT_RUNNING",
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요.",
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요.",
        )

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ante.ipc.exceptions import IPCTimeoutError

        exc = self._send(monkeypatch, side_effect=IPCTimeoutError("slow"))
        assert type(exc).__name__ == "IPCClientTimeoutError"
        assert (exc.ipc_error_code, exc.ipc_error_message, exc.message) == (  # type: ignore[attr-defined]
            "IPC_TIMEOUT",
            "서버 응답 시간 초과",
            "서버 응답 시간 초과",
        )

    @pytest.mark.parametrize(
        ("error", "code", "message"),
        [
            (
                {"code": "BOT_NOT_FOUND", "message": "봇 없음"},
                "BOT_NOT_FOUND",
                "봇 없음",
            ),
            (
                {"code": "TRADE_ERROR", "message": "체결 실패"},
                "TRADE_ERROR",
                "체결 실패",
            ),
            ({}, "UNKNOWN", "알 수 없는 오류"),
        ],
    )
    def test_remote_error_keeps_server_code(
        self, monkeypatch: pytest.MonkeyPatch, error: dict, code: str, message: str
    ) -> None:
        exc = self._send(monkeypatch, return_value={"status": "error", "error": error})
        assert type(exc).__name__ == "IPCRemoteError"
        assert (exc.code, exc.ipc_error_code, exc.ipc_error_message, exc.message) == (  # type: ignore[attr-defined]
            code,
            code,
            message,
            f"{code}: {message}",
        )

    @pytest.mark.parametrize(
        ("name", "spec"),
        [
            (
                "IPCServerNotRunningError",
                ("IPC_SERVER_NOT_RUNNING", "service_unavailable", 1),
            ),
            ("IPCClientTimeoutError", ("IPC_TIMEOUT", "service_unavailable", 1)),
        ],
    )
    def test_two_client_codes_are_registered(
        self, name: str, spec: tuple[str, str, int]
    ) -> None:
        from ante.contracts import ipc_client_errors
        from ante.contracts.error_registry import EXCEPTION_TO_SPEC

        registered = EXCEPTION_TO_SPEC[getattr(ipc_client_errors, name)]
        assert (registered.code, registered.category, registered.exit_code) == spec

    def test_success_returns_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ante.cli.commands import ipc_helpers

        monkeypatch.setattr(
            ipc_helpers, "get_socket_path", lambda config_dir=None: "/x.sock"
        )
        monkeypatch.setattr(
            ipc_helpers.IPCClient,
            "send",
            AsyncMock(return_value={"status": "ok", "result": {"n": 1}}),
        )
        assert asyncio.run(ipc_helpers.ipc_send("bot.list", {})) == {"n": 1}

    @pytest.mark.parametrize(
        ("side_effect", "code", "message"),
        [
            (
                "not-running",
                "IPC_SERVER_NOT_RUNNING",
                "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요.",
            ),
            ("timeout", "IPC_TIMEOUT", "서버 응답 시간 초과"),
        ],
    )
    def test_cli_json_envelope_for_ipc_failures(
        self,
        monkeypatch: pytest.MonkeyPatch,
        inject,
        side_effect: str,
        code: str,
        message: str,
    ) -> None:
        """명령이 ``ipc_send``의 예외를 그대로 올려도 봉투의 코드가 같다."""
        from ante.cli.commands import ipc_helpers
        from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError

        raised = (
            ServerNotRunningError("x")
            if side_effect == "not-running"
            else IPCTimeoutError("x")
        )
        monkeypatch.setattr(
            ipc_helpers, "get_socket_path", lambda config_dir=None: "/x.sock"
        )
        monkeypatch.setattr(
            ipc_helpers.IPCClient, "send", AsyncMock(side_effect=raised)
        )

        def _callback(*args: object, **kwargs: object) -> None:
            asyncio.run(ipc_helpers.ipc_send("bot.list", {}))

        cmd = _leaf(("bot", "list"))
        monkeypatch.setattr(cmd, "params", [])
        monkeypatch.setattr(cmd, "callback", _callback)
        result = _invoke(["--format", "json", "bot", "list"])
        _assert_json_exit(result, code, message)


# ── IPC _dispatch의 매핑 ──────────────────────────────────────────────────


class TestDispatchMapping:
    def _response(self, exc: BaseException) -> dict:
        return _dispatch_raising(exc)

    @pytest.mark.parametrize(
        ("exc", "error"),
        [
            pytest.param(
                _UnclassifiedError("boom"),
                {"code": "EXECUTION_ERROR", "message": "boom"},
                id="unclassified",
            ),
            pytest.param(
                type("_Int", (Exception,), {"code": 500})("http 500"),
                {"code": "EXECUTION_ERROR", "message": "http 500"},
                id="integer-code",
            ),
            pytest.param(
                type("_Coded", (Exception,), {"code": "SOME_DOMAIN_CODE"})("coded"),
                {"code": "SOME_DOMAIN_CODE", "message": "coded"},
                id="code-attribute",
            ),
        ],
    )
    def test_error_payload(self, exc: BaseException, error: dict) -> None:
        assert self._response(exc) == {"id": "r1", "status": "error", "error": error}

    def test_registered_exception(self) -> None:
        from ante.bot.exceptions import BotNotFoundError

        assert self._response(BotNotFoundError("bot-x")) == {
            "id": "r1",
            "status": "error",
            "error": {"code": "BOT_NOT_FOUND", "message": "Bot not found: bot-x"},
        }

    def test_registry_wins_over_code_attribute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ante.contracts.error_registry import EXCEPTION_TO_SPEC
        from ante.contracts.errors import ErrorSpec

        coded = type("_Coded", (Exception,), {"code": "ATTRIBUTE_CODE"})
        monkeypatch.setitem(
            EXCEPTION_TO_SPEC,
            coded,
            ErrorSpec(code="REGISTRY_CODE", category="internal"),
        )
        assert self._response(coded("m"))["error"] == {
            "code": "REGISTRY_CODE",
            "message": "m",
        }

    def test_expected_reject_code_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from ante.bot.exceptions import BotNotRunning

        with caplog.at_level("WARNING", logger="ante.ipc.server"):
            response = self._response(BotNotRunning("bot-x", "stopped"))
        assert response["error"]["code"] == "BOT_NOT_RUNNING"
        records = [
            (r.levelname, r.getMessage())
            for r in caplog.records
            if r.name == "ante.ipc.server"
        ]
        assert records == [
            ("WARNING", "IPC handshake rejected: test.raise (BOT_NOT_RUNNING)")
        ]

    def test_unexpected_code_logs_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger="ante.ipc.server"):
            self._response(_UnclassifiedError("boom"))
        records = [
            (r.levelname, r.getMessage())
            for r in caplog.records
            if r.name == "ante.ipc.server"
        ]
        assert records == [("ERROR", "IPC 커맨드 실행 오류: test.raise")]
