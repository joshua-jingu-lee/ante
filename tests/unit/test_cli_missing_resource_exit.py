"""CLI missing-resource 경로의 nonzero exit code 보장 테스트 (#1515).

이슈 #1515 (oracle A7 cli_lookup_errors_exit_zero):
``trade info``, ``config get``, ``bot info``, ``bot signal-key``, ``member info``
5개 조회 명령이 missing-resource를 JSON error로 출력하면서도 exit code 0으로
종료되던 ingress drift를 닫는다. 각 호출자가 ``fmt.error(...)`` 출력 후
``ctx.exit(1)``을 호출해 nonzero exit를 강제한다.

분류 메모:
- ``trade info``, ``config get``, ``member info``는 offline CLI (IPC route 없음).
- ``bot info`` / ``bot signal-key``는 spec ``docs/specs/cli/03-commands.md``상
  ``runtime IPC + snapshot fallback`` 분류이지만, 본 PR의 target 경로(missing case)는
  DB 직접 조회 경로 — IPC 동작 변경 없음.
- ``report view``, ``treasury snapshot``도 같은 ``fmt.error(...) ; return`` 패턴이
  잔존하지만 oracle probe signature에 미포함되어 본 PR Non-Goals (follow-up 후보).
- ``Formatter.error()`` 자체는 미변경 — ``strategy validate`` 등 ``fmt.error`` 후
  추가 errors/warnings를 계속 출력하는 호출자 회귀 회피.

``ante signal connect`` 연결 실패 exit code 회귀 (#1560):
``signal connect``의 ``_run_connect``(``src/ante/cli/commands/signal.py``)에는
연결 실패 가드 4개가 모두 ``_err(...)``(stderr 출력) 후 ``return``으로 끝나
process exit code가 0으로 남던 결함이 있었다(oracle A7 probe:
invalid key가 ``Invalid signal key``를 stderr로 내면서 returncode 0).

자동화 호출자는 process exit code를 1차 신호로 사용하므로 연결 실패는
non-zero exit이어야 한다. 4개 가드(invalid key / bot not found / bot not
running / 시그널 미수용)는 모두 동일 invariant("signal connect 연결 실패
→ exit 1")를 공유하므로 한쪽만 고치면 실패 사유별 exit code가 갈린다
(#1557 narrow-scope 선례: 동일 결함 분기 일괄 정렬, half-fix 회피).
4개 가드 전부 ``raise SystemExit(1)``로 정렬되며, ``_err`` stderr 메시지·
문구는 그대로 유지(streaming 명령 — JSON envelope 비대상)되고, 정상 경로
(``_err("Connected ...")`` 안내 후 ``channel.run()`` 정상 반환 → exit 0)는
불변임을 ``TestSignalConnect*`` 에서 회귀 보장한다.

``signal_connect``는 ``asyncio.run(_run_connect(key))``만 호출하므로
``SystemExit(1)``이 ``finally: await db.close()`` 실행 후 asyncio.run
경계를 통해 process exit code 1로 전파됨을 CliRunner exit_code로 확인한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture()
def runner() -> CliRunner:
    """인증을 mock으로 우회한 CliRunner.

    stderr/stdout 분리(``mix_stderr=False``)로 text 모드 ``Error:`` 메시지가
    stderr로 가는지 확인 가능하게 한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


# ── trade info ───────────────────────────────────────────


class TestTradeInfoMissingExit:
    """``ante trade info <missing>`` 은 exit 1 + JSON error envelope."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = MagicMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(
                cli, ["trade", "info", "nonexistent-trade", "--format", "json"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-trade" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(cli, ["trade", "info", "nonexistent-trade"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 trade는 exit 0으로 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            return_value={
                "trade_id": "t-1",
                "bot_id": "b-1",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 10,
                "price": 150.0,
                "status": "filled",
            }
        )

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(cli, ["trade", "info", "t-1", "--format", "json"])

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["trade_id"] == "t-1"


# ── config get ───────────────────────────────────────────


class TestConfigGetMissingExit:
    """``ante config get <missing.key>`` 은 exit 1 (caller-level exit)."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None  # static 조회 실패
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli, ["config", "get", "nonexistent.key", "--format", "json"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent.key" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(cli, ["config", "get", "nonexistent.key"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 static config 키는 exit 0으로 회귀 보존."""
        mock_config = MagicMock()
        mock_config.get.return_value = "hello"
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli, ["config", "get", "some.key", "--format", "json"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["key"] == "some.key"
        assert payload["value"] == "hello"
        assert payload["source"] == "static"


# ── bot info ─────────────────────────────────────────────


class TestBotInfoMissingExit:
    """``ante bot info <missing>`` 은 exit 1.

    target 경로는 DB 직접 조회 (`bot.py:128`) — IPC 분기 미경유.
    """

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "info", "nonexistent-bot"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-bot" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(cli, ["bot", "info", "nonexistent-bot"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 봇은 exit 0으로 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            return_value={
                "bot_id": "b-1",
                "name": "test-bot",
                "strategy_id": "s-1",
                "account_id": "a-1",
                "status": "active",
                "created_at": "2026-01-01T00:00:00",
            }
        )

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(cli, ["bot", "info", "b-1"])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "b-1" in result.stdout


# ── bot signal-key ───────────────────────────────────────


class TestBotSignalKeyMissingExit:
    """``ante bot signal-key <bot-without-key>`` 은 exit 1."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value=None)

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "bot-without-key"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "bot-without-key" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value=None)

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(cli, ["bot", "signal-key", "bot-without-key"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """signal_key 존재 시 exit 0 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value="sk_test123")

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "signal-key", "b-1"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["signal_key"] == "sk_test123"


# ── member info ──────────────────────────────────────────


class TestMemberInfoMissingExit:
    """``ante member info <missing>`` 은 exit 1."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=None)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "info", "nonexistent-member"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-member" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=None)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["member", "info", "nonexistent-member"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 member는 exit 0 회귀 보존."""
        existing = Member(
            member_id="m-1",
            type=MemberType.HUMAN,
            role=MemberRole.DEFAULT,
            org="default",
            name="Existing",
            status="active",
            scopes=[],
        )
        svc = MagicMock()
        svc.get = AsyncMock(return_value=existing)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "member", "info", "m-1"])

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["member_id"] == "m-1"


# ── signal connect 연결 실패 exit code (#1560) ────────────


def _invoke_signal_connect(
    runner: CliRunner,
    *,
    bot_id: str | None,
    bot: object | None,
    channel_runs: bool = False,
) -> object:
    """``signal connect``의 의존성을 mock한 뒤 invoke한다.

    ``_run_connect``는 함수 로컬 import로 ``Database``/``SignalKeyManager``/
    ``BotManager``/``SignalChannel``/``get_db_path``를 resolve하므로 각 원본
    모듈 속성을 패치하면 결정적으로 가드 분기를 탄다.

    Args:
        bot_id: ``SignalKeyManager.validate_key`` 반환값. ``None``이면
            invalid-key 가드.
        bot: ``BotManager.get_bot`` 반환값. ``None``이면 bot-not-found 가드.
            객체면 status/strategy 속성으로 나머지 가드를 제어한다.
        channel_runs: ``True``면 ``SignalChannel.run``을 정상 반환 mock으로
            교체해 정상 경로(exit 0)를 검증한다.
    """
    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()

    mock_skm = MagicMock()
    mock_skm.initialize = AsyncMock()
    mock_skm.validate_key = AsyncMock(return_value=bot_id)

    mock_manager = MagicMock()
    mock_manager.initialize = AsyncMock()
    mock_manager.get_bot = MagicMock(return_value=bot)

    mock_channel = MagicMock()
    mock_channel.run = AsyncMock(return_value=None)

    with (
        patch("ante.core.database.Database", return_value=mock_db),
        patch(
            "ante.bot.signal_key.SignalKeyManager",
            return_value=mock_skm,
        ),
        patch(
            "ante.bot.manager.BotManager",
            return_value=mock_manager,
        ),
        patch(
            "ante.bot.signal_channel.SignalChannel",
            return_value=mock_channel,
        ),
    ):
        return runner.invoke(cli, ["signal", "connect", "--key", "sk_probe"])


def _running_bot(*, accepts_external_signals: bool) -> MagicMock:
    """RUNNING 상태 + 지정한 시그널 수용 여부를 가진 bot mock."""
    from ante.bot.config import BotStatus

    bot = MagicMock()
    bot.status = BotStatus.RUNNING
    bot.strategy = MagicMock()
    bot.strategy.meta = MagicMock()
    bot.strategy.meta.accepts_external_signals = accepts_external_signals
    bot._ctx = MagicMock()
    return bot


class TestSignalConnectInvalidKeyExit:
    """``signal connect --key <invalid>`` 은 exit 1 + stderr (#1560 결함 재현).

    결함 시점에는 ``Invalid signal key``를 stderr로 내면서 returncode 0이었다.
    """

    def test_invalid_key_exits_nonzero(self, runner: CliRunner) -> None:
        result = _invoke_signal_connect(runner, bot_id=None, bot=None)

        assert result.exit_code == 1, (
            f"expected exit 1 for invalid key, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Invalid signal key" in result.stderr, result.stderr


class TestSignalConnectBotNotFoundExit:
    """키는 유효하나 봇이 없으면 exit 1 + stderr ``Bot not found:`` (#1560)."""

    def test_bot_not_found_exits_nonzero(self, runner: CliRunner) -> None:
        result = _invoke_signal_connect(runner, bot_id="bot-1", bot=None)

        assert result.exit_code == 1, (
            f"expected exit 1 for missing bot, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Bot not found: bot-1" in result.stderr, result.stderr


class TestSignalConnectBotNotRunningExit:
    """봇이 RUNNING이 아니면 exit 1 + stderr ``Bot is not running:`` (#1560)."""

    def test_bot_not_running_exits_nonzero(self, runner: CliRunner) -> None:
        from ante.bot.config import BotStatus

        bot = MagicMock()
        bot.status = BotStatus.STOPPED

        result = _invoke_signal_connect(runner, bot_id="bot-1", bot=bot)

        assert result.exit_code == 1, (
            f"expected exit 1 for non-running bot, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Bot is not running: bot-1" in result.stderr, result.stderr


class TestSignalConnectRejectsExternalSignalsExit:
    """전략이 외부 시그널을 수용하지 않으면 exit 1 + stderr (#1560)."""

    def test_not_accepting_signals_exits_nonzero(self, runner: CliRunner) -> None:
        bot = _running_bot(accepts_external_signals=False)

        result = _invoke_signal_connect(runner, bot_id="bot-1", bot=bot)

        assert result.exit_code == 1, (
            f"expected exit 1 for signal-rejecting bot, "
            f"got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Bot bot-1 does not accept external signals" in result.stderr, (
            result.stderr
        )


class TestSignalConnectSuccessPathKeepsExit0:
    """contract-drift 가드: 정상 연결·종료는 기존 계약(exit 0) 유지 (#1560).

    4개 실패 가드를 ``raise SystemExit(1)``로 정렬하되, 정상 경로
    (``_err("Connected ...")`` 안내 후 ``channel.run()`` 정상 반환)는
    blanket "signal connect → exit 1"로 번지지 않고 exit 0을 유지해야 한다.
    """

    def test_channel_run_returns_keeps_exit_0(self, runner: CliRunner) -> None:
        bot = _running_bot(accepts_external_signals=True)

        result = _invoke_signal_connect(
            runner, bot_id="bot-1", bot=bot, channel_runs=True
        )

        assert result.exit_code == 0, (
            f"expected exit 0 for normal channel close, "
            f"got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # 안내용 _err은 실패가 아니므로 그대로 stderr로 나간다.
        assert "Connected to bot bot-1" in result.stderr, result.stderr
