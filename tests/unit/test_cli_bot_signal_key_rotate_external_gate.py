"""Refs #1761 — ``bot signal-key --rotate`` accepts_external_signals 게이트.

## 배경

오라클 host probe ``cli_signal_key_rotate_accepts_external_contract`` (A7)
는 ``accepts_external_signals=False`` 전략의 봇에 대해서도
``bot signal-key --rotate`` 가 ``returncode=0`` 으로 새 키를 발급하고,
이어지는 조회에서 ``after_key_present=true`` 가 관측되는 invariant 위반을
보고했다. 외부 신호를 받지 않아야 할 봇에 인증 키가 생겨 운영자가 전략의
외부 신호 허용 상태를 잘못 이해할 수 있다.

Root cause (사실):
1. ``ante/cli/commands/bot.py`` 의 ``bot_signal_key`` ``--rotate`` 분기가
   ``skm.rotate(bot_id)`` 호출 전에 전략의 ``accepts_external_signals``
   메타를 확인하지 않았다.
2. ``BotManager.rotate_signal_key`` 도 동일 게이트를 적용하지 않아 IPC /
   server-side 경로에서도 같은 회귀가 가능했다.
3. 비교: ``BotManager.create_bot`` 의 자동 발급 분기는 정확히
   ``getattr(strategy_cls.meta, "accepts_external_signals", False)`` 일 때만
   ``signal_key_manager.generate(bot_id)`` 를 호출 — rotate 가 같은 invariant
   를 따르지 않아 일관성이 깨졌다.

## 회귀 lock

Refs #2111: ``bot signal-key --rotate`` 는 runtime IPC
(``bot.signal_key.rotate``) 전용으로 라우팅된다. CLI cold-path 의 직접
``SignalKeyManager.rotate`` 호출과 in-CLI accepts_external_signals 게이트는
제거되었다. accepts_external_signals invariant 는 서버
``BotManager.rotate_signal_key`` (R5) 가 단일 chokepoint 로 적용하며, CLI
표면은 ``ipc_send`` 의 server envelope 을 surface 한다.

- R1 (회귀 보존 — external strategy): external 전략 봇의 정상 rotate 는
  ``ipc_send`` 가 ``{rotated:True, signal_key}`` envelope 을 반환하고 CLI 가
  exit 0 + IPC envelope passthrough 로 surface 한다.
- R2 (게이트 — non-external strategy): non-external 전략 봇은 서버가
  ``BotNotAcceptingSignals`` → ``BOT_NOT_ACCEPTING_SIGNALS`` envelope 을
  반환하고, CLI 가 exit 1 + ``code="BOT_NOT_ACCEPTING_SIGNALS"`` 로 보존한다.
- R3 (orphan 차단): R2 조건에서 CLI 는 ``SignalKeyManager`` 를 직접 호출하지
  않는다 (cold-path 미사용 회귀 — orphan credential 미발급은 서버 게이트
  R5 가 책임).
- R4 (sanity): non-rotate get 경로는 게이트 적용 대상 아님 — 기존 키 조회는
  정상 동작 (read cold-path 회귀 보존).
- R5 (BotManager 게이트): ``BotManager.rotate_signal_key`` 가 동일 invariant
  를 raise ``BotNotAcceptingSignals`` (code=``BOT_NOT_ACCEPTING_SIGNALS``) 로
  적용 — runtime IPC / server-side 경로의 단일 chokepoint.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.bot.config import BotConfig
from ante.bot.exceptions import (
    BOT_NOT_ACCEPTING_SIGNALS_CODE,
    BotNotAcceptingSignals,
)
from ante.bot.manager import BotManager
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.base import Signal, Strategy, StrategyMeta


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
    """인증을 mock으로 우회한 CliRunner (test_cli_missing_resource_exit 동형)."""
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


class _AcceptingStrategy(Strategy):
    """accepts_external_signals=True 전략."""

    meta = StrategyMeta(
        name="accepting",
        version="1.0.0",
        description="accepts external signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:  # type: ignore[override]
        return []


class _NormalStrategy(Strategy):
    """accepts_external_signals=False 전략."""

    meta = StrategyMeta(
        name="normal",
        version="1.0.0",
        description="non-external strategy",
    )

    async def on_step(self, context: dict) -> list[Signal]:  # type: ignore[override]
        return []


# ── R1: 회귀 보존 ─────────────────────────────────────


class TestRotateExternalStrategyAllowed:
    """R1: external 전략 봇의 정상 rotate 는 IPC envelope passthrough (#2111)."""

    def test_rotate_external_strategy_exits_zero_with_key(
        self, runner: CliRunner
    ) -> None:
        mock_send = AsyncMock(
            return_value={
                "bot_id": "bot-ext-1",
                "signal_key": "sk_external_rotated_42",
                "rotated": True,
            }
        )
        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "signal-key",
                    "bot-ext-1",
                    "--rotate",
                ],
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        # JSON 모드는 IPC envelope passthrough (raw_legacy, bot start 동형).
        payload = json.loads(result.stdout)
        assert payload["signal_key"] == "sk_external_rotated_42"
        assert payload["rotated"] is True
        mock_send.assert_awaited_once()
        assert mock_send.await_args.args[0] == "bot.signal_key.rotate"
        assert mock_send.await_args.args[1] == {"bot_id": "bot-ext-1"}


# ── R2 + R3: 게이트 + orphan 차단 ─────────────────────


class TestRotateNonExternalStrategyRejected:
    """R2/R3: non-external 전략 봇은 서버 게이트가 거부, CLI 는 envelope surface
    + cold-path 미사용 (#2111)."""

    def _not_accepting_click_exc(self) -> object:
        """서버 ``BotNotAcceptingSignals`` → ``BOT_NOT_ACCEPTING_SIGNALS``
        envelope 을 ``ipc_send`` 가 변환한 ClickException 을 모사한다."""
        import click

        message = (
            "이 봇의 전략은 외부 시그널을 받지 않습니다: "
            "bot_id=bot-normal-1, strategy_id=normal-1"
        )
        exc = click.ClickException(f"{BOT_NOT_ACCEPTING_SIGNALS_CODE}: {message}")
        exc.ipc_error_code = BOT_NOT_ACCEPTING_SIGNALS_CODE  # type: ignore[attr-defined]
        exc.ipc_error_message = message  # type: ignore[attr-defined]
        return exc

    def _guard_skm(self) -> AsyncMock:
        """직접 호출되면 즉시 실패하는 SignalKeyManager mock.

        R3 회귀: rotate 는 cold-path 를 거치지 않고 IPC 로만 라우팅되므로
        ``SignalKeyManager`` 가 CLI 에서 직접 호출되어선 안 된다 (orphan
        credential 미발급은 서버 게이트 R5 책임).
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError(
                "rotate cold-path 가 호출됨 (#2111: IPC 전용이어야 함)"
            )
        )
        skm.get_key = AsyncMock()
        return skm

    def test_rotate_non_external_strategy_exits_one_with_code_json(
        self, runner: CliRunner
    ) -> None:
        click_exc = self._not_accepting_click_exc()

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._guard_skm()
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
                    "bot-normal-1",
                    "--rotate",
                ],
            )

        # R2: exit 1 + JSON envelope 의 안정된 code.
        assert result.exit_code == 1, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == BOT_NOT_ACCEPTING_SIGNALS_CODE
        assert payload["code"] == "BOT_NOT_ACCEPTING_SIGNALS"
        assert "외부 시그널을 받지 않습니다" in payload["message"]
        # R3: CLI 가 SignalKeyManager 를 직접 호출하지 않는다 (cold-path 미사용).
        mock_skm.rotate.assert_not_awaited()

    def test_rotate_non_external_strategy_exits_one_text(
        self, runner: CliRunner
    ) -> None:
        """text 모드에서도 동일 거부 — exit 1 + stderr ``Error:``."""
        click_exc = self._not_accepting_click_exc()

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        mock_skm = self._guard_skm()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli, ["bot", "signal-key", "bot-normal-1", "--rotate"]
            )

        assert result.exit_code == 1, result.stdout + result.stderr
        assert "Error:" in result.stderr
        assert "외부 시그널을 받지 않습니다" in result.stderr
        mock_skm.rotate.assert_not_awaited()


# ── R4: sanity — non-rotate get 경로는 게이트 적용 대상 아님 ───


class TestNonRotateGetUnaffectedByGate:
    """R4: 게이트는 ``--rotate`` 분기 전용 — 키 조회 경로는 회귀 보존."""

    def test_get_key_non_external_strategy_returns_existing_key(
        self, runner: CliRunner
    ) -> None:
        """non-external 전략이라도 이미 발급된 키 조회는 정상 (#1761 비대상).

        게이트는 발급 차단 invariant. 기존 키 조회는 운영상 의도된 동작이며,
        게이트가 키 조회까지 막으면 회귀 (#1596과 동일 분리 원칙).
        """
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "normal-1"})
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value="sk_already_present_99")

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
                cli, ["--format", "json", "bot", "signal-key", "bot-normal-1"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["signal_key"] == "sk_already_present_99"
        mock_skm.get_key.assert_awaited_once_with("bot-normal-1")


# ── R5: BotManager 게이트 (defense-in-depth) ────────


def _make_bot_manager(signal_key_manager: MagicMock) -> BotManager:
    """server-side BotManager 인스턴스 (test_bot_create_signal_key_auto 동형)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.execute_script = AsyncMock()
    eventbus = MagicMock()
    eventbus.subscribe = MagicMock()
    return BotManager(eventbus=eventbus, db=db, signal_key_manager=signal_key_manager)


@pytest.mark.asyncio
class TestBotManagerRotateSignalKeyGate:
    """R5: ``BotManager.rotate_signal_key`` 도 동일 invariant 를 raise."""

    async def test_rotate_non_external_strategy_raises_typed_exception(
        self,
    ) -> None:
        """non-external 전략 봇 → ``BotNotAcceptingSignals`` raise, rotate
        미호출."""
        skm = MagicMock()
        skm.rotate = AsyncMock(return_value="sk_should_not_be_called")

        manager = _make_bot_manager(skm)
        config = BotConfig(
            bot_id="bot-mgr-normal",
            strategy_id="normal",
            account_id="acc-test",
        )
        await manager.create_bot(config, _NormalStrategy, ctx=MagicMock())

        with pytest.raises(BotNotAcceptingSignals) as exc_info:
            await manager.rotate_signal_key("bot-mgr-normal")

        # IPC server.py envelope 정렬을 위한 안정된 code attribute.
        assert exc_info.value.code == BOT_NOT_ACCEPTING_SIGNALS_CODE
        # 게이트가 키 발급을 차단해 orphan credential 미발급.
        skm.rotate.assert_not_called()

    async def test_rotate_external_strategy_delegates_to_skm(self) -> None:
        """sanity: external 전략은 회귀 보존 — ``skm.rotate(bot_id)`` 호출."""
        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_auto")
        skm.rotate = AsyncMock(return_value="sk_mgr_rotated")

        manager = _make_bot_manager(skm)
        config = BotConfig(
            bot_id="bot-mgr-ext",
            strategy_id="accepting",
            account_id="acc-test",
        )
        await manager.create_bot(config, _AcceptingStrategy, ctx=MagicMock())

        new_key = await manager.rotate_signal_key("bot-mgr-ext")

        assert new_key == "sk_mgr_rotated"
        skm.rotate.assert_awaited_once_with("bot-mgr-ext")
