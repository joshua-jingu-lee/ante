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

- R1 (회귀 보존 — external strategy): ``accepts_external_signals=True`` 전략의
  봇은 ``--rotate`` 가 exit 0 + ``rotated=True`` envelope, ``skm.rotate``
  호출됨.
- R2 (게이트 — non-external strategy): ``accepts_external_signals=False``
  전략의 봇은 ``--rotate`` 가 exit 1 + ``code="BOT_NOT_ACCEPTING_SIGNALS"``
  envelope.
- R3 (orphan 차단): R2 조건에서 ``skm.rotate`` 가 **호출되지 않는다**
  (게이트가 키 발급 자체를 차단해 orphan credential 미발급).
- R4 (sanity): non-rotate get 경로는 게이트 적용 대상 아님 — 기존 키 조회는
  정상 동작 (회귀 보존).
- R5 (BotManager 게이트): ``BotManager.rotate_signal_key`` 가 동일 invariant
  를 raise ``BotNotAcceptingSignals`` (code=``BOT_NOT_ACCEPTING_SIGNALS``) 로
  적용 — IPC / server-side 경로의 defense-in-depth.
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


def _make_strategy_patches(*, accepts_external_signals: bool) -> tuple:
    """``StrategyRegistry`` + ``StrategyLoader.load`` patch tuple 을 생성한다.

    rotate 게이트가 봇의 ``strategy_id`` 로 registry 조회 → ``StrategyLoader``
    로 클래스 로드 → ``meta.accepts_external_signals`` 확인하는 경로를
    단위 테스트에서 시뮬레이션한다.
    """
    mock_record = MagicMock()
    mock_record.filepath = "/fake/path.py"
    mock_registry = AsyncMock()
    mock_registry.initialize = AsyncMock()
    mock_registry.get = AsyncMock(return_value=mock_record)

    mock_strategy_cls = MagicMock()
    mock_strategy_cls.meta = StrategyMeta(
        name="t",
        version="1.0.0",
        description="t",
        accepts_external_signals=accepts_external_signals,
    )

    return (
        patch(
            "ante.strategy.registry.StrategyRegistry",
            return_value=mock_registry,
        ),
        patch(
            "ante.strategy.loader.StrategyLoader.load",
            return_value=mock_strategy_cls,
        ),
    )


# ── R1: 회귀 보존 ─────────────────────────────────────


class TestRotateExternalStrategyAllowed:
    """R1: ``accepts_external_signals=True`` 전략 봇은 rotate 정상."""

    def test_rotate_external_strategy_exits_zero_with_key(
        self, runner: CliRunner
    ) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "ext-1"})
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.rotate = AsyncMock(return_value="sk_external_rotated_42")

        reg_patch, loader_patch = _make_strategy_patches(accepts_external_signals=True)
        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new=_acm_factory((mock_db, None, None, None)),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
            reg_patch,
            loader_patch,
        ):
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
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["signal_key"] == "sk_external_rotated_42"
        assert payload["data"]["rotated"] is True
        mock_skm.rotate.assert_awaited_once_with("bot-ext-1")


# ── R2 + R3: 게이트 + orphan 차단 ─────────────────────


class TestRotateNonExternalStrategyRejected:
    """R2/R3: non-external 전략 봇은 rotate 거부 + skm.rotate 미호출."""

    def _gated_skm(self) -> AsyncMock:
        """rotate 가 호출되면 즉시 실패하는 SignalKeyManager mock.

        R3 검증의 핵심: 게이트가 ``skm.rotate`` **이전** 에 걸려야 한다.
        ``assert_not_awaited`` 와 함께 이중으로 orphan 미발급을 lock 한다.
        """
        skm = AsyncMock()
        skm.initialize = AsyncMock()
        skm.rotate = AsyncMock(
            side_effect=AssertionError(
                "non-external 전략인데 rotate 가 호출됨 (orphan credential)"
            )
        )
        skm.get_key = AsyncMock()
        return skm

    def test_rotate_non_external_strategy_exits_one_with_code_json(
        self, runner: CliRunner
    ) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "normal-1"})
        mock_skm = self._gated_skm()

        reg_patch, loader_patch = _make_strategy_patches(accepts_external_signals=False)
        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new=_acm_factory((mock_db, None, None, None)),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
            reg_patch,
            loader_patch,
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
        # R3: 게이트가 키 발급을 차단 — skm.rotate 미호출 (orphan 미발급).
        mock_skm.rotate.assert_not_awaited()

    def test_rotate_non_external_strategy_exits_one_text(
        self, runner: CliRunner
    ) -> None:
        """text 모드에서도 동일 거부 — exit 1 + stderr ``Error:``."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "normal-1"})
        mock_skm = self._gated_skm()

        reg_patch, loader_patch = _make_strategy_patches(accepts_external_signals=False)
        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new=_acm_factory((mock_db, None, None, None)),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
            reg_patch,
            loader_patch,
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
