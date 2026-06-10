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
(``_err("Connected ...")`` 안내 후 채널 종료 → exit 0)는 불변임을
``TestSignalConnect*`` 에서 회귀 보장한다.

#2338 마이그레이션: ``signal connect`` 가 in-process ``Database``/``BotManager``/
``SignalChannel`` 구성에서 **데몬-위임 thin IPC relay** 로 재작성됐다. 따라서
본 #1560 invariant 테스트도 4 게이트의 in-process patch(Database/SignalKey
Manager/BotManager/SignalChannel)를 **IPC-layer mock** 으로 repoint 한다 —
``asyncio.open_unix_connection`` 을 fake reader/writer 로 교체하고, 데몬
Phase-B 응답 프레임(error/ok)을 직접 주입해 exit-1(가드)·exit-0(정상 종료)
invariant 를 byte-identical 로 유지한다. ``signal_connect`` 가
``asyncio.run(_run_connect)`` 만 호출하므로 ``SystemExit(1)`` 이 asyncio.run
경계를 통해 process exit code 1 로 전파됨을 CliRunner exit_code 로 확인한다.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType


def _acm_factory(value):  # noqa: ANN001, ANN202
    """#1857: helper async context manager 전환에 맞춰 fake factory 를
    생성한다. 기존 ``new_callable=AsyncMock, return_value=(...)`` 패턴을
    ``new=_acm_factory((...))`` 로 대체해 ``async with helper(ctx) as
    (...):`` 호출이 yield 한 값을 그대로 받도록 한다.
    """
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _fake_factory(*args, **kwargs):
        yield value

    return _fake_factory


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
            new=_acm_factory((mock_config, mock_dynamic, mock_db)),
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
            new=_acm_factory((mock_config, mock_dynamic, mock_db)),
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
            new=_acm_factory((mock_config, mock_dynamic, mock_db)),
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
            new=_acm_factory((mock_db, None, None, None)),
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
            new=_acm_factory((mock_db, None, None, None)),
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
            new=_acm_factory((mock_db, None, None, None)),
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
                new=_acm_factory((mock_db, None, None, None)),
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
                new=_acm_factory((mock_db, None, None, None)),
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
                new=_acm_factory((mock_db, None, None, None)),
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
        """실재 bot --rotate 재발급은 exit 0 + IPC 라우팅 + standard envelope.

        Refs #2111: rotate 는 runtime IPC (``bot.signal_key.rotate``) 전용으로
        라우팅된다. 단, 출력 계약(standard envelope ``{status, message, data}``,
        json/text 공통)은 그대로 보존된다 — cli_registry signal-key 계약의
        문서화·drift-test 된 mixed-branch 결정. 라우팅 변경이 출력-shape 변경이
        아님을 lock 한다. 존재 확인 / accepts_external_signals 게이트는 서버
        ``BotManager.rotate_signal_key`` 가 단일 chokepoint 로 수행한다.
        """
        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(
                return_value={
                    "bot_id": "b-1",
                    "signal_key": "sk_rotated999",
                    "rotated": True,
                }
            ),
        ) as mock_send:
            result = runner.invoke(
                cli, ["--format", "json", "bot", "signal-key", "b-1", "--rotate"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        # 출력 계약 보존: standard envelope (``{status, message, data}``).
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["signal_key"] == "sk_rotated999"
        assert payload["data"]["rotated"] is True
        # rotate 는 runtime IPC (``bot.signal_key.rotate``) 로 라우팅된다.
        mock_send.assert_awaited_once()
        assert mock_send.await_args.args[0] == "bot.signal_key.rotate"
        assert mock_send.await_args.args[1] == {"bot_id": "b-1"}


class TestBotSignalKeyMissingBotExit:
    """``ante bot signal-key <missing-bot>`` 은 exit 1 (#1596 / #2111).

    미존재 bot 에 대한 signal key 조회/재발급을 차단한다 (oracle A7
    missing-resource). 형제 명령(`bot info`/`bot remove`/`bot positions`,
    #1558)과 동일하게 "봇을 찾을 수 없습니다: {bot_id}" + exit 1 +
    ``BOT_NOT_FOUND`` code 로 거부하고, orphan credential 을 발급하지 않는다.

    read (조회, rotate 미지정) 경로는 ``_create_services()`` 의 ``Database``
    직접 조회 (``SELECT ... FROM bots WHERE bot_id = ?``) cold-path 가
    그대로 가드한다 — ``SignalKeyManager`` 자체는 미변경 (Non-Goal).

    Refs #2111: ``--rotate`` 는 runtime IPC (``bot.signal_key.rotate``)
    전용으로 라우팅되므로, 미존재 bot 거부는 서버
    ``BotManager.rotate_signal_key`` 의 ``BotNotFoundError`` →
    ``BOT_NOT_FOUND`` envelope 으로 일어난다. 본 클래스의 rotate 케이스는
    ``ipc_send`` 가 server envelope 을 surface 하는 CLI 라우팅만 lock 하고,
    orphan 미발급 invariant 는 서버 handler/manager 테스트가 책임진다.
    """

    def _missing_skm(self) -> AsyncMock:
        """get_key 가 호출되면 즉시 실패하는 SignalKeyManager mock.

        read 경로 미존재 bot 가드가 ``skm.get_key`` **이전**에 걸리므로,
        이 mock 의 메서드는 호출되어선 안 된다 (orphan credential 미조회
        검증). rotate 는 cold-path 를 거치지 않으므로 (#2111 IPC 전용)
        ``rotate`` 도 동일하게 미호출이어야 한다.
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError(
                "rotate cold-path 가 호출됨 (#2111: IPC 전용이어야 함)"
            )
        )
        skm.get_key = AsyncMock(
            side_effect=AssertionError("미존재 bot 인데 get_key 가 호출됨")
        )
        return skm

    def test_missing_bot_rotate_exits_nonzero_json(self, runner: CliRunner) -> None:
        """#2111: 미존재 bot --rotate → 서버 ``BOT_NOT_FOUND`` envelope 을
        ``ipc_send`` 가 surface, CLI 가 exit 1 + ``BOT_NOT_FOUND`` 로 보존."""
        click_exc = click.ClickException(
            "BOT_NOT_FOUND: 봇을 찾을 수 없습니다: oracle-missing-bot"
        )
        click_exc.ipc_error_code = "BOT_NOT_FOUND"  # type: ignore[attr-defined]
        click_exc.ipc_error_message = (  # type: ignore[attr-defined]
            "봇을 찾을 수 없습니다: oracle-missing-bot"
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._missing_skm()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
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
        # 서버 ``BotNotFoundError.code`` 와 동형 stable code.
        assert payload["code"] == "BOT_NOT_FOUND"
        # cold-path 미사용 회귀: 직접 DB rotate/get_key 미호출.
        mock_skm.rotate.assert_not_awaited()
        mock_skm.get_key.assert_not_awaited()

    def test_missing_bot_rotate_exits_nonzero_text(self, runner: CliRunner) -> None:
        """#2111: text 모드에서도 서버 envelope 을 surface (exit 1 + stderr)."""
        click_exc = click.ClickException(
            "BOT_NOT_FOUND: 봇을 찾을 수 없습니다: oracle-missing-bot"
        )
        click_exc.ipc_error_code = "BOT_NOT_FOUND"  # type: ignore[attr-defined]
        click_exc.ipc_error_message = (  # type: ignore[attr-defined]
            "봇을 찾을 수 없습니다: oracle-missing-bot"
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._missing_skm()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
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
                new=_acm_factory((mock_db, None, None, None)),
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
                new=_acm_factory((mock_db, None, None, None)),
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

        Refs #2111: 본 정규화는 read (조회) cold-path 가 책임지므로 rotate
        플래그 없이 read 경로로 lock 한다 (rotate 는 IPC 전용으로 이전).
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
                new=_acm_factory((mock_db, None, None, None)),
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
                ],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다: oracle-missing-bot" in payload["message"]
        mock_skm.get_key.assert_not_awaited()

    def test_other_operational_error_not_swallowed(self, runner: CliRunner) -> None:
        """``no such table`` 외 ``OperationalError`` 는 미존재로 정규화하지
        않고 그대로 전파(일반 에러 경로 → exit 1, 거부 메시지 아님).

        Refs #2111: read (조회) cold-path 의 에러 정규화 회귀이므로 rotate
        플래그 없이 lock 한다.
        """
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
                new=_acm_factory((mock_db, None, None, None)),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "some-bot"],
            )

        # malformed db 는 미존재 bot 으로 둔갑하지 않는다 (메시지 구분).
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "봇을 찾을 수 없습니다" not in payload["message"]
        # non-"no such table" OperationalError 는 non-zero exit (#1596).
        assert result.exit_code != 0, result.output
        mock_skm.get_key.assert_not_awaited()

    def test_db_error_exits_nonzero_json(self, runner: CliRunner) -> None:
        """bot 존재확인 중 non-"no such table" ``OperationalError`` (locked/
        malformed DB) 발생 시 → JSON error + **exit code != 0** (#1596).

        finding 회귀 고정: 결함 시점에는 ``except Exception`` 핸들러가
        ``fmt.error(str(e)); return`` 으로 끝나 JSON error 를 내고도 process
        exit code 가 0 으로 남아 자동화 호출자가 실패를 감지하지 못했다.
        형제 ``bot remove`` (raise SystemExit(1) from e)와 동일하게 non-zero
        exit 으로 정렬한다. 미존재 bot 거부 경로(exit 1 "봇을 찾을 수
        없습니다")는 별도 invariant 로 그대로 유지된다.

        Refs #2111: read (조회) cold-path 의 DB 오류 exit-code 회귀이므로
        rotate 플래그 없이 lock 한다 (rotate 는 IPC 전용으로 이전).
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
                new=_acm_factory((mock_db, None, None, None)),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "some-bot"],
            )

        # 핵심 회귀 assert: DB 오류는 non-zero exit 으로 끝나야 한다.
        assert result.exit_code != 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        # locked DB 는 미존재 bot 으로 둔갑하지 않는다 (거부 메시지 아님).
        assert "봇을 찾을 수 없습니다" not in payload["message"]
        # orphan credential 미조회: get_key 미호출 (가드 이전 실패).
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
                new=_acm_factory((mock_db, None, None, None)),
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
    ("봇을 찾을 수 없습니다" + exit 1 + ``BOT_NOT_FOUND``), orphan 미발급.

    Refs #2111: read (조회) cold-path 의 ``status != 'deleted'`` SELECT 가드
    회귀는 ``test_soft_deleted_bot_lookup_*`` 가 보존한다. ``--rotate`` 는
    runtime IPC (``bot.signal_key.rotate``) 전용으로 이전되었으므로,
    soft-deleted bot rotate 거부는 서버 ``BotManager.rotate_signal_key`` 의
    ``BotNotFoundError`` → ``BOT_NOT_FOUND`` envelope 으로 일어나며 (server
    ``load_from_db`` 도 ``WHERE status != 'deleted'`` 정렬), rotate 케이스는
    ``ipc_send`` 의 server envelope surface 만 lock 한다.
    """

    def _missing_skm(self) -> AsyncMock:
        """get_key 가 호출되면 즉시 실패하는 SignalKeyManager mock.

        read 경로 soft-deleted bot 가드가 ``skm.get_key`` **이전**에 걸리므로,
        이 mock 의 메서드는 호출되어선 안 된다 (orphan credential 미조회
        검증). rotate 는 cold-path 를 거치지 않으므로 (#2111 IPC 전용)
        ``rotate`` 도 동일하게 미호출이어야 한다.
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError(
                "rotate cold-path 가 호출됨 (#2111: IPC 전용이어야 함)"
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

    def _bot_not_found_click_exc(self) -> click.ClickException:
        """서버 ``BotNotFoundError`` → ``BOT_NOT_FOUND`` envelope 을 ``ipc_send``
        가 변환한 ClickException 을 모사한다."""
        exc = click.ClickException(
            "BOT_NOT_FOUND: 봇을 찾을 수 없습니다: soft-deleted-bot"
        )
        exc.ipc_error_code = "BOT_NOT_FOUND"  # type: ignore[attr-defined]
        exc.ipc_error_message = (  # type: ignore[attr-defined]
            "봇을 찾을 수 없습니다: soft-deleted-bot"
        )
        return exc

    def test_soft_deleted_bot_rotate_exits_nonzero_json(
        self, runner: CliRunner
    ) -> None:
        """#2111: soft-deleted bot --rotate → 서버 ``BOT_NOT_FOUND`` envelope
        을 ``ipc_send`` 가 surface, CLI 가 exit 1 + ``BOT_NOT_FOUND`` 로 보존."""
        click_exc = self._bot_not_found_click_exc()

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._missing_skm()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
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
        # 서버 ``BotNotFoundError.code`` 와 동형 stable code.
        assert payload["code"] == "BOT_NOT_FOUND"
        # cold-path 미사용 회귀: 직접 DB rotate/get_key 미호출.
        mock_skm.rotate.assert_not_awaited()
        mock_skm.get_key.assert_not_awaited()

    def test_soft_deleted_bot_rotate_exits_nonzero_text(
        self, runner: CliRunner
    ) -> None:
        """#2111: text 모드에서도 서버 envelope 을 surface (exit 1 + stderr)."""
        click_exc = self._bot_not_found_click_exc()

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._missing_skm()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
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
                new=_acm_factory((mock_db, None, None, None)),
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
                new=_acm_factory((mock_db, None, None, None)),
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


def _signal_frame(d: dict) -> bytes:
    """dict → length-prefixed wire 프레임 ([4B big-endian len][UTF-8 JSON])."""
    import struct

    payload = json.dumps(d, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


class _SignalFakeReader:
    """미리 framed bytes 를 ``readexactly`` 로 슬라이스 제공하는 reader 대역.

    소진 시 ``IncompleteReadError`` 를 raise 해 socket EOF 를 모사한다.
    """

    def __init__(self, frames: list[bytes]) -> None:
        import asyncio

        self._asyncio = asyncio
        self._buf = b"".join(frames)
        self._pos = 0

    async def readexactly(self, n: int):  # noqa: ANN202
        if self._pos + n > len(self._buf):
            partial = self._buf[self._pos :]
            self._pos = len(self._buf)
            raise self._asyncio.IncompleteReadError(partial, n)
        chunk = self._buf[self._pos : self._pos + n]
        self._pos += n
        return chunk


class _SignalFakeWriter:
    """write/drain/write_eof/close/wait_closed no-op writer 대역."""

    def write(self, data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def write_eof(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def _invoke_signal_connect(
    runner: CliRunner,
    *,
    bot_id: str | None,
    bot: object | None,
    channel_runs: bool = False,
) -> object:
    """``signal connect`` 의 IPC transport 를 mock 한 뒤 invoke 한다 (#2338).

    재작성된 ``_run_connect`` 는 데몬-위임 thin relay 이므로 in-process
    Database/SignalKeyManager/BotManager/SignalChannel patch 대신, 데몬이
    보냈을 **Phase-B 응답 프레임** 을 ``asyncio.open_unix_connection`` fake
    transport 로 주입한다. ``bot_id``/``bot`` 인자는 어느 게이트가 발화했을지를
    결정해 그에 대응하는 데몬 error envelope(byte-identical code/message)을
    구성한다 — exit-1(가드)·exit-0(정상) invariant 는 유지된다.

    Args:
        bot_id: invalid-key 게이트 결정. ``None`` 이면 ``INVALID_SIGNAL_KEY``.
        bot: bot-not-found / 상태 게이트 결정. ``None`` 이면 ``BOT_NOT_FOUND``,
            객체면 status/strategy 속성으로 BOT_NOT_RUNNING /
            BOT_NOT_ACCEPTING_SIGNALS 를 결정한다.
        channel_runs: ``True`` 면 OK + closed frame 을 주입해 정상 종료(exit 0).
    """
    import asyncio

    from ante.bot.config import BotStatus

    # 데몬 4-게이트 동형으로 어느 거부 프레임을 주입할지 결정한다.
    if bot_id is None:
        frame = {
            "id": "h1",
            "status": "error",
            "error": {"code": "INVALID_SIGNAL_KEY", "message": "Invalid signal key"},
        }
    elif bot is None:
        frame = {
            "id": "h1",
            "status": "error",
            "error": {
                "code": "BOT_NOT_FOUND",
                "message": f"Bot not found: {bot_id}",
            },
        }
    elif getattr(bot, "status", None) != BotStatus.RUNNING:
        status_value = bot.status.value
        frame = {
            "id": "h1",
            "status": "error",
            "error": {
                "code": "BOT_NOT_RUNNING",
                "message": f"Bot is not running: {bot_id} (status: {status_value})",
            },
        }
    elif not getattr(bot.strategy.meta, "accepts_external_signals", False):
        frame = {
            "id": "h1",
            "status": "error",
            "error": {
                "code": "BOT_NOT_ACCEPTING_SIGNALS",
                "message": f"Bot {bot_id} does not accept external signals",
            },
        }
    else:
        # 모든 게이트 통과 — OK handshake.
        frame = {
            "id": "h1",
            "status": "ok",
            "result": {"bot_id": bot_id, "account_id": "acc", "session_id": "s1"},
        }

    frames = [_signal_frame(frame)]
    if channel_runs:
        frames.append(_signal_frame({"type": "closed", "reason": "eof"}))

    reader = _SignalFakeReader(frames)
    writer = _SignalFakeWriter()

    async def _open(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        return reader, writer

    async def _idle_pump_in(_writer):  # noqa: ANN001, ANN202
        # 정상 경로(channel_runs)에서 가짜 stdin 의 connect_read_pipe 부작용을
        # 피하고 ``_pump_out`` 이 closed frame 으로 종료를 주도하게 한다.
        await asyncio.Event().wait()

    with (
        patch("ante.cli.commands.signal.Path.exists", return_value=True),
        patch(
            "ante.cli.commands.signal.get_socket_path",
            return_value="/tmp/test-ante.sock",
        ),
        patch("asyncio.open_unix_connection", _open),
        patch("ante.cli.commands.signal._pump_in", _idle_pump_in),
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
