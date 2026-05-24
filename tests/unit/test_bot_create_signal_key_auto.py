"""Refs #1760 — accepts_external_signals 전략 bot create 시 signal key 자동 발급 회귀.

## 배경

오라클 host probe ``cli_signal_key_auto_generation_contract`` (A7) 가
``accepts_external_signals=True`` 전략으로 ``bot create`` 후 ``bot
signal-key`` 조회가 "시그널 키가 없습니다" 로 실패하는 invariant
위반을 보고했다.

Root cause: ``BotManager.__init__`` 의 ``signal_key_manager`` 인자가
optional 이고, ``BotManager.create_bot`` 의 자동 발급 분기
(``manager.py:427-431``) 가 ``self._signal_key_manager`` truthy 일 때만
``generate(bot_id)`` 를 호출한다. 그러나 server-side composition root
``ante.main._init_trading`` (``main.py:424``) 가 ``BotManager`` 생성 시
``signal_key_manager`` 를 주입하지 않아 ``_signal_key_manager=None`` 으로
남고 자동 발급이 항상 skip 됐다 (CLI ``bot create`` 는 IPC 경유 →
server-side BotManager 사용).

## 회귀 lock

- R1 (소스 invariant): ``ante.main._init_trading`` 가 ``BotManager`` 에
  ``signal_key_manager=`` kwarg 와 ``SignalKeyManager`` 인스턴스화/initialize
  를 포함하도록 강제한다. 누군가 다시 주입을 제거하면 이 test 가
  실패한다.
- R2 (동작 — external): ``SignalKeyManager`` 가 주입된 ``BotManager``
  에서 ``accepts_external_signals=True`` 전략 bot 을 생성하면
  ``signal_key_manager.generate(bot_id)`` 가 호출된다.
- R3 (sanity — non-external): 같은 ``BotManager`` 에서
  ``accepts_external_signals=False`` 전략은 ``generate`` 가 호출되지
  않는다 (기존 분기 보존).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

import ante.main as main_module
from ante.bot.config import BotConfig
from ante.bot.manager import BotManager
from ante.strategy.base import Signal, Strategy, StrategyMeta


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


# ── R1: 소스 invariant lock ─────────────────────────────


class TestServerSideInitTradingInjectsSignalKeyManager:
    """Refs #1760: ``ante.main._init_trading`` 가 ``BotManager`` 에
    ``signal_key_manager`` 를 주입한다는 사실을 소스 레벨에서 lock 한다.

    server-side composition root 가 주입을 누락하면 ``BotManager.create_bot``
    의 자동 발급 분기가 skip 되어 external signal 전략의 ``bot signal-key``
    조회가 실패한다 (root cause).
    """

    def test_init_trading_imports_signal_key_manager(self) -> None:
        """``_init_trading`` 함수가 ``SignalKeyManager`` 를 import 한다."""
        source = inspect.getsource(main_module._init_trading)
        assert "from ante.bot.signal_key import SignalKeyManager" in source, (
            "Refs #1760: server-side _init_trading 가 SignalKeyManager import 를"
            " 잃으면 BotManager.signal_key_manager 가 None 으로 남아 외부 시그널"
            " 전략의 bot create 자동 발급이 skip 된다."
        )

    def test_init_trading_instantiates_signal_key_manager_with_db(self) -> None:
        """``SignalKeyManager(db=s.db)`` 인스턴스화가 존재한다."""
        source = inspect.getsource(main_module._init_trading)
        assert "SignalKeyManager(db=s.db)" in source, (
            "Refs #1760: SignalKeyManager 는 server-side Database 인스턴스(s.db)"
            " 로 만들어야 cold-path CLI ``bot signal-key`` 와 같은 SQLite 파일을"
            " 공유한다."
        )

    def test_init_trading_initializes_signal_key_manager(self) -> None:
        """``SignalKeyManager.initialize()`` 가 await 된다."""
        source = inspect.getsource(main_module._init_trading)
        assert "await signal_key_manager.initialize()" in source, (
            "Refs #1760: signal_keys 테이블이 없으면 generate(bot_id) INSERT 가"
            " 실패한다. initialize() 호출이 누락되면 회귀."
        )

    def test_init_trading_passes_signal_key_manager_kwarg_to_bot_manager(
        self,
    ) -> None:
        """``BotManager(..., signal_key_manager=signal_key_manager)`` kwarg
        가 BotManager 생성에 전달된다."""
        source = inspect.getsource(main_module._init_trading)
        assert "signal_key_manager=signal_key_manager" in source, (
            "Refs #1760: BotManager 생성 시 signal_key_manager kwarg 가 누락되면"
            " BotManager._signal_key_manager=None 으로 남아 create_bot 자동"
            " 발급 분기 (manager.py:427-431) 가 영원히 skip 된다."
        )


# ── R2 / R3: 동작 검증 ─────────────────────────────


def _make_bot_manager(signal_key_manager: MagicMock) -> BotManager:
    """``signal_key_manager`` 가 주입된 BotManager 인스턴스를 만든다.

    server-side composition root (``ante.main._init_trading``) 가
    ``BotManager(..., signal_key_manager=signal_key_manager)`` 로 부르는
    동일한 주입 패턴을 시뮬레이션한다.
    """

    db = MagicMock()
    db.execute = AsyncMock()
    db.execute_script = AsyncMock()
    eventbus = MagicMock()
    eventbus.subscribe = MagicMock()

    return BotManager(eventbus=eventbus, db=db, signal_key_manager=signal_key_manager)


@pytest.mark.asyncio
class TestCreateBotAutoGeneratesSignalKey:
    """Refs #1760: server-side 주입 패턴 회귀."""

    async def test_external_signal_strategy_triggers_generate(self) -> None:
        """accepts_external_signals=True 전략 bot create → generate(bot_id)
        호출됨 (R2)."""
        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_auto_generated_test_key_R2")

        manager = _make_bot_manager(skm)
        config = BotConfig(
            bot_id="bot-external-1",
            strategy_id="accepting",
            account_id="acc-test",
        )

        await manager.create_bot(config, _AcceptingStrategy, ctx=MagicMock())

        skm.generate.assert_awaited_once_with("bot-external-1")

    async def test_non_external_signal_strategy_skips_generate(self) -> None:
        """accepts_external_signals=False 전략 bot create → generate 호출
        안 됨 (R3 sanity, 기존 분기 보존)."""
        skm = MagicMock()
        skm.generate = AsyncMock()

        manager = _make_bot_manager(skm)
        config = BotConfig(
            bot_id="bot-normal-1",
            strategy_id="normal",
            account_id="acc-test",
        )

        await manager.create_bot(config, _NormalStrategy, ctx=MagicMock())

        skm.generate.assert_not_called()
