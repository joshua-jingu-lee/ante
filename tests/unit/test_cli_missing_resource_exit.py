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

``ante bot signal-key <missing-bot>`` orphan credential 거부 (#1596):
``bot signal-key``는 #1515에서 "키 없음(실재 bot)" missing-key만 exit 1로
정렬됐으나, 미존재 bot에 대해서는 ``skm.rotate``/``skm.get_key``가 그대로
호출되어 orphan signal key가 발급/조회되고 exit 0으로 종료되던 결함이
잔존했다(oracle A7 missing-resource). 형제 명령(`bot info`/`bot remove`/
`bot positions`, #1558)과 동일하게 rotate/get_key **이전**에 ``SELECT 1
FROM bots WHERE bot_id = ?``로 bot 존재를 확인하고, 미존재면 "봇을 찾을
수 없습니다: {bot_id}" + exit 1 (code 없음)로 거부한다. 미존재 sentinel
처리는 기존 ``signal_key is None``("시그널 키가 없습니다") 분기보다 먼저
와서 미존재 bot이 "키 없음"으로 잘못 빠지지 않게 한다. ``SignalKeyManager``
자체와 다른 bot 서브커맨드는 미변경 (Non-Goal).

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
from contextlib import asynccontextmanager
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


def _patch_member_factory(svc):  # noqa: ANN001, ANN202
    """#1856: ``member._create_service`` async context manager fake factory."""

    @asynccontextmanager
    async def _fake_factory(ctx=None):  # noqa: ANN001, ANN202
        yield svc

    return patch(
        "ante.cli.commands.member._create_service",
        new=_fake_factory,
    )


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
    """``ante bot signal-key <bot-without-key>`` 은 exit 1.

    "키 없음(실재 bot)" 경로의 회귀 보존. 미존재 bot 거부(#1596)는
    ``TestBotSignalKeyMissingBotExit``에서 별도 검증한다 — 두 케이스는
    서로 다른 invariant("키 없음" vs "봇 없음")라 메시지/문구가 다르다.
    """

    def test_missing_key_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        # 실재 bot (bots row 존재) 이지만 signal key 미발급 상태.
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})
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
        # #1808: 실재 bot 의 키 없음 → typed code ``SIGNAL_KEY_NOT_SET`` +
        # "signal key가 설정되지 않았습니다" (이전 "시그널 키가 없습니다").
        # 미존재 bot 거부(#1596 → BOT_NOT_FOUND)와 envelope code 로 의미
        # 구분된다.
        assert "signal key가 설정되지 않았습니다" in payload["message"]
        assert payload.get("code") == "SIGNAL_KEY_NOT_SET"

    def test_missing_key_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})
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
        # #1808: text 모드는 envelope code 없이 메시지만 — 새 wording 정렬.
        assert "signal key가 설정되지 않았습니다" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """signal_key 존재 시 exit 0 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})
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

    def test_valid_rotate_exits_zero(self, runner: CliRunner) -> None:
        """실재 bot --rotate 재발급은 exit 0 + rotated 회귀 보존.

        Refs #1761: rotate 분기가 ``strategy_id`` 를 함께 SELECT 하고
        ``accepts_external_signals`` 게이트를 통과해야 ``skm.rotate`` 가
        호출된다. ``StrategyRegistry``/``StrategyLoader`` 를 patch 해
        external signals=True 전략을 시뮬레이션한다.
        """
        from ante.strategy.base import StrategyMeta

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "s-1"})
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.rotate = AsyncMock(return_value="sk_rotated999")

        mock_record = MagicMock()
        mock_record.filepath = "/fake/path.py"
        mock_registry = AsyncMock()
        mock_registry.initialize = AsyncMock()
        mock_registry.get = AsyncMock(return_value=mock_record)

        mock_strategy_cls = MagicMock()
        mock_strategy_cls.meta = StrategyMeta(
            name="ext",
            version="1.0.0",
            description="external",
            accepts_external_signals=True,
        )

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
            patch(
                "ante.strategy.registry.StrategyRegistry",
                return_value=mock_registry,
            ),
            patch(
                "ante.strategy.loader.StrategyLoader.load",
                return_value=mock_strategy_cls,
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "signal-key", "b-1", "--rotate"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        # rotate 성공은 ``fmt.success`` envelope: {status:ok, message, data}.
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["signal_key"] == "sk_rotated999"
        assert payload["data"]["rotated"] is True
        mock_skm.rotate.assert_awaited_once_with("b-1")


class TestBotSignalKeyMissingBotExit:
    """``ante bot signal-key <missing-bot> [--rotate]`` 은 exit 1 (#1596).

    미존재 bot 에 대한 signal key 발급/조회를 차단한다 (oracle A7
    missing-resource). 형제 명령(`bot info`/`bot remove`/`bot positions`,
    #1558)과 동일하게 "봇을 찾을 수 없습니다: {bot_id}" + exit 1, **에러
    코드 없음**으로 거부하고, orphan credential 을 발급하지 않는다.

    target 경로는 ``_create_services()`` 의 ``Database`` 직접 조회
    (``SELECT 1 FROM bots WHERE bot_id = ?``) — ``SignalKeyManager``
    자체는 미변경 (Non-Goal).
    """

    def _missing_skm(self) -> AsyncMock:
        """rotate/get_key 가 호출되면 즉시 실패하는 SignalKeyManager mock.

        미존재 bot 가드가 ``skm.rotate``/``skm.get_key`` **이전**에
        걸리므로, 이 mock 의 메서드는 호출되어선 안 된다 (orphan
        credential 미발급 검증).
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError("미존재 bot 인데 rotate 가 호출됨 (orphan)")
        )
        skm.get_key = AsyncMock(
            side_effect=AssertionError("미존재 bot 인데 get_key 가 호출됨")
        )
        return skm

    def test_missing_bot_rotate_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)  # bots row 없음
        mock_skm = self._missing_skm()

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
                [
                    "--format",
                    "json",
                    "bot",
                    "signal-key",
                    "oracle-missing-bot",
                    "--rotate",
                ],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in payload["message"]
        # #1784 Group A sweep: 미존재 bot 은 안정 코드 ``BOT_NOT_FOUND`` 로
        # surface 한다 (CLI/IPC 일관성: ``BotNotFoundError.code`` 와 동형).
        # 이전 #1558 의 "code 없음" 계약은 #1784 oracle A7 evidence 에서
        # 자동화 분류 불가 결함으로 보고되어 본 sweep 에서 폐기.
        assert payload["code"] == "BOT_NOT_FOUND"
        # orphan credential 미발급: rotate 가 호출되지 않았어야 한다.
        mock_skm.rotate.assert_not_awaited()
        mock_skm.get_key.assert_not_awaited()

    def test_missing_bot_rotate_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_skm = self._missing_skm()

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
                cli, ["bot", "signal-key", "oracle-missing-bot", "--rotate"]
            )

        assert result.exit_code == 1
        assert "Error:" in result.stderr
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in result.stderr
        mock_skm.rotate.assert_not_awaited()

    def test_missing_bot_lookup_exits_nonzero_json(self, runner: CliRunner) -> None:
        """미존재 bot + rotate 없음(키 조회)도 exit 1 + 동일 메시지."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_skm = self._missing_skm()

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
                ["--format", "json", "bot", "signal-key", "oracle-missing-bot"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in payload["message"]
        # 미존재 bot 이 "시그널 키가 없습니다" 로 잘못 빠지지 않아야 한다.
        assert "시그널 키가 없습니다" not in payload["message"]
        # #1784 Group A sweep: 안정 코드 ``BOT_NOT_FOUND`` 로 surface.
        assert payload["code"] == "BOT_NOT_FOUND"
        mock_skm.get_key.assert_not_awaited()

    def test_missing_bot_lookup_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)
        mock_skm = self._missing_skm()

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
            result = runner.invoke(cli, ["bot", "signal-key", "oracle-missing-bot"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in result.stderr
        mock_skm.get_key.assert_not_awaited()

    def test_missing_bot_no_such_table_normalized(self, runner: CliRunner) -> None:
        """``bots`` 테이블 부재 → 미존재 bot 으로 정규화 (#1558 동형).

        ``no such table`` ``OperationalError`` 는 정의상 해당 bot_id 가
        존재할 수 없으므로 미존재 bot 과 동일하게 exit 1 + 거부 메시지.
        """
        import sqlite3

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("no such table: bots")
        )
        mock_skm = self._missing_skm()

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
                [
                    "--format",
                    "json",
                    "bot",
                    "signal-key",
                    "oracle-missing-bot",
                    "--rotate",
                ],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in payload["message"]
        mock_skm.rotate.assert_not_awaited()

    def test_other_operational_error_not_swallowed(self, runner: CliRunner) -> None:
        """``no such table`` 외 ``OperationalError`` 는 미존재로 정규화하지
        않고 그대로 전파(일반 에러 경로 → exit 1, 거부 메시지 아님)."""
        import sqlite3

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("database disk image is malformed")
        )
        mock_skm = self._missing_skm()

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
                ["--format", "json", "bot", "signal-key", "some-bot", "--rotate"],
            )

        # malformed db 는 미존재 bot 으로 둔갑하지 않는다 (메시지 구분).
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다" not in payload["message"]
        # non-"no such table" OperationalError 는 non-zero exit (#1596).
        assert result.exit_code != 0, result.output
        mock_skm.rotate.assert_not_awaited()

    def test_db_error_exits_nonzero_json(self, runner: CliRunner) -> None:
        """bot 존재확인 중 non-"no such table" ``OperationalError`` (locked/
        malformed DB) 발생 시 → JSON error + **exit code != 0** (#1596).

        finding 회귀 고정: 결함 시점에는 ``except Exception`` 핸들러가
        ``fmt.error(str(e)); return`` 으로 끝나 JSON error 를 내고도 process
        exit code 가 0 으로 남아 자동화 호출자가 실패를 감지하지 못했다.
        형제 ``bot remove`` (raise SystemExit(1) from e)와 동일하게 non-zero
        exit 으로 정렬한다. 미존재 bot 거부 경로(exit 1 "봇을 찾을 수
        없습니다", code 없음)는 별도 invariant 로 그대로 유지된다.
        """
        import sqlite3

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        mock_skm = self._missing_skm()

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
                ["--format", "json", "bot", "signal-key", "some-bot", "--rotate"],
            )

        # 핵심 회귀 assert: DB 오류는 non-zero exit 으로 끝나야 한다.
        assert result.exit_code != 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        # locked DB 는 미존재 bot 으로 둔갑하지 않는다 (거부 메시지 아님).
        assert "봇을 찾을 수 없습니다" not in payload["message"]
        # orphan credential 미발급: rotate/get_key 미호출 (가드 이전 실패).
        mock_skm.rotate.assert_not_awaited()
        mock_skm.get_key.assert_not_awaited()

    def test_db_error_exits_nonzero_text(self, runner: CliRunner) -> None:
        """text 모드에서도 DB 오류 → stderr ``Error:`` + exit code != 0."""
        import sqlite3

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        mock_skm = self._missing_skm()

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
            result = runner.invoke(cli, ["bot", "signal-key", "some-bot"])

        assert result.exit_code != 0, result.output
        assert "Error:" in result.stderr
        assert "봇을 찾을 수 없습니다" not in result.stderr
        mock_skm.get_key.assert_not_awaited()


class TestBotSignalKeySoftDeletedBotExit:
    """soft-deleted bot 은 운영상 미존재로 거부 (#1596 attempt2).

    ``bot remove`` 는 키 폐기 후 ``UPDATE bots SET status = 'deleted'``
    (soft delete, manager.py:826) 하므로 ``bots`` row 가 남는다. row
    존재만 확인하던 ``SELECT 1 FROM bots WHERE bot_id = ?`` 는 이를
    통과시켜 ``--rotate`` 가 삭제된 봇에 orphan credential 을 재발급했다
    (#1596가 막으려는 버그류).

    수정: 존재확인에 ``AND status != 'deleted'`` 추가 →
    ``BotManager.load_from_db`` 의 운영 bot 정의(manager.py:212
    ``FROM bots WHERE status != 'deleted'``)와 정렬. soft-deleted bot 은
    row 없는 미존재 bot 과 동일한 missing sentinel → 동일 거부
    ("봇을 찾을 수 없습니다" + exit 1, code 없음), orphan 미발급.
    """

    def _missing_skm(self) -> AsyncMock:
        """rotate/get_key 가 호출되면 즉시 실패하는 SignalKeyManager mock.

        soft-deleted bot 가드가 ``skm.rotate``/``skm.get_key`` **이전**에
        걸리므로, 이 mock 의 메서드는 호출되어선 안 된다 (orphan
        credential 미발급 검증).
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError(
                "soft-deleted bot 인데 rotate 가 호출됨 (orphan 재발급)"
            )
        )
        skm.get_key = AsyncMock(
            side_effect=AssertionError("soft-deleted bot 인데 get_key 가 호출됨")
        )
        return skm

    def _soft_deleted_db(self) -> AsyncMock:
        """soft-deleted bot 을 모사하는 ``Database`` mock.

        쿼리 SQL 을 검사해 ``status != 'deleted'`` 필터가 실제로
        적용되는지 회귀 고정한다. 필터가 빠진 옛 쿼리
        (``WHERE bot_id = ?``) 면 row 가 반환되어 orphan 가드를
        통과 → ``skm`` AssertionError 로 테스트가 실패한다.
        """
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        async def fetch_one(query: str, params: tuple) -> dict | None:
            normalized = " ".join(query.lower().split())
            # bots row 는 존재하나 status='deleted'. 운영 bot 필터가
            # 적용된 쿼리만 None(미존재) 을 돌려준다.
            if "status != 'deleted'" in normalized:
                return None
            return {"1": 1}

        mock_db.fetch_one = AsyncMock(side_effect=fetch_one)
        return mock_db

    def test_soft_deleted_bot_rotate_exits_nonzero_json(
        self, runner: CliRunner
    ) -> None:
        mock_db = self._soft_deleted_db()
        mock_skm = self._missing_skm()

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
                [
                    "--format",
                    "json",
                    "bot",
                    "signal-key",
                    "soft-deleted-bot",
                    "--rotate",
                ],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: soft-deleted-bot" in payload["message"]
        # #1784 Group A sweep: 미존재 bot 과 동일 형제 계약 — 안정 코드
        # ``BOT_NOT_FOUND`` 로 surface (이전 #1558 의 "code 없음" 폐기).
        assert payload["code"] == "BOT_NOT_FOUND"
        # orphan credential 미발급: rotate 가 호출되지 않았어야 한다.
        mock_skm.rotate.assert_not_awaited()
        mock_skm.get_key.assert_not_awaited()

    def test_soft_deleted_bot_rotate_exits_nonzero_text(
        self, runner: CliRunner
    ) -> None:
        mock_db = self._soft_deleted_db()
        mock_skm = self._missing_skm()

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
                cli, ["bot", "signal-key", "soft-deleted-bot", "--rotate"]
            )

        assert result.exit_code == 1
        assert "Error:" in result.stderr
        assert "봇을 찾을 수 없습니다: soft-deleted-bot" in result.stderr
        mock_skm.rotate.assert_not_awaited()

    def test_soft_deleted_bot_lookup_exits_nonzero_json(
        self, runner: CliRunner
    ) -> None:
        """soft-deleted bot + rotate 없음(키 조회)도 exit 1 + 동일 메시지."""
        mock_db = self._soft_deleted_db()
        mock_skm = self._missing_skm()

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
                ["--format", "json", "bot", "signal-key", "soft-deleted-bot"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: soft-deleted-bot" in payload["message"]
        # soft-deleted bot 이 "시그널 키가 없습니다" 로 잘못 빠지지 않아야 한다.
        assert "시그널 키가 없습니다" not in payload["message"]
        # #1784 Group A sweep: 안정 코드 ``BOT_NOT_FOUND`` 로 surface.
        assert payload["code"] == "BOT_NOT_FOUND"
        mock_skm.get_key.assert_not_awaited()

    def test_soft_deleted_bot_lookup_exits_nonzero_text(
        self, runner: CliRunner
    ) -> None:
        mock_db = self._soft_deleted_db()
        mock_skm = self._missing_skm()

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
            result = runner.invoke(cli, ["bot", "signal-key", "soft-deleted-bot"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr
        assert "봇을 찾을 수 없습니다: soft-deleted-bot" in result.stderr
        mock_skm.get_key.assert_not_awaited()


# ── member info ──────────────────────────────────────────


class TestMemberInfoMissingExit:
    """``ante member info <missing>`` 은 exit 1."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=None)

        with _patch_member_factory(svc):
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

        with _patch_member_factory(svc):
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

        with _patch_member_factory(svc):
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
