"""accepts_external_signals 플래그 및 외부 시그널 수신 테스트."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.bot.config import BotStatus
from ante.eventbus.events import ExternalSignalEvent
from ante.strategy.base import Signal, Strategy, StrategyMeta
from ante.strategy.validator import StrategyValidator

# ── US-1: StrategyMeta accepts_external_signals ──────────


class TestStrategyMetaFlag:
    """StrategyMeta accepts_external_signals 필드 테스트."""

    def test_default_false(self) -> None:
        """기본값은 False."""
        meta = StrategyMeta(name="test", version="1.0.0", description="test")
        assert meta.accepts_external_signals is False

    def test_set_true(self) -> None:
        """True로 설정 가능."""
        meta = StrategyMeta(
            name="test",
            version="1.0.0",
            description="test",
            accepts_external_signals=True,
        )
        assert meta.accepts_external_signals is True

    def test_backward_compatible(self) -> None:
        """기존 전략 코드에 영향 없음."""
        meta = StrategyMeta(
            name="old_strategy",
            version="1.0.0",
            description="legacy",
            author="human",
            symbols=["005930"],
            timeframe="1d",
        )
        assert meta.accepts_external_signals is False


class TestValidatorExternalSignals:
    """StrategyValidator accepts_external_signals 경고 테스트."""

    def _write_strategy(self, code: str) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write(code)
        f.close()
        return Path(f.name)

    def test_no_warning_without_flag(self) -> None:
        """accepts_external_signals 없으면 경고 없음."""
        path = self._write_strategy(
            """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class MyStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0", description="test")

    async def on_step(self, context):
        return []
"""
        )
        result = StrategyValidator().validate(path)
        assert result.valid
        assert not any("accepts_external_signals" in w for w in result.warnings)

    def test_warning_with_flag_no_on_data(self) -> None:
        """accepts_external_signals=True + on_data() 미구현 시 경고."""
        path = self._write_strategy(
            """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class MyStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0", description="test",
        accepts_external_signals=True,
    )

    async def on_step(self, context):
        return []
"""
        )
        result = StrategyValidator().validate(path)
        assert result.valid
        assert any("accepts_external_signals" in w for w in result.warnings)
        assert any("on_data" in w for w in result.warnings)

    def test_no_warning_with_flag_and_on_data(self) -> None:
        """accepts_external_signals=True + on_data() 구현 시 경고 없음."""
        path = self._write_strategy(
            """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class MyStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0", description="test",
        accepts_external_signals=True,
    )

    async def on_step(self, context):
        return []

    async def on_data(self, data):
        return []
"""
        )
        result = StrategyValidator().validate(path)
        assert result.valid
        assert not any("accepts_external_signals" in w for w in result.warnings)


# ── US-2: Bot.on_external_signal() ──────────────────────


class _InhouseStrategy(Strategy):
    """accepts_external_signals=False 전략."""

    meta = StrategyMeta(name="inhouse", version="1.0.0", description="inhouse strategy")

    async def on_step(self, context: dict) -> list[Signal]:
        return []


class _OutsourcedStrategy(Strategy):
    """accepts_external_signals=True 전략."""

    meta = StrategyMeta(
        name="outsourced",
        version="1.0.0",
        description="outsourced strategy",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        return [
            Signal(
                symbol=data["symbol"],
                side=data["action"],
                quantity=1.0,
                reason=data.get("reason", "external"),
            )
        ]


def _make_bot(strategy_cls: type[Strategy]) -> MagicMock:
    """Bot 인스턴스를 만들되 필요한 속성을 mock으로 설정."""
    from ante.bot.bot import Bot

    config = MagicMock()
    config.bot_id = "bot-001"
    config.strategy_id = "stg-001"
    config.account_id = "test"

    ctx = MagicMock()
    ctx.get_positions.return_value = {}
    ctx.get_balance.return_value = {"available": 1000000.0}

    eventbus = MagicMock()
    eventbus.publish = AsyncMock()

    bot = Bot(config=config, strategy_cls=strategy_cls, ctx=ctx, eventbus=eventbus)
    bot.strategy = strategy_cls(ctx=ctx)
    # #2337: on_external_signal 이 상태 재검증(RUNNING 아니면 거부)한다(#2333
    # daemon-side fix). start() 없이 on_data 발화를 테스트하려면 RUNNING 을
    # 명시해야 한다(이전엔 default CREATED 였으나 가드 미존재로 통과했다).
    bot.status = BotStatus.RUNNING

    return bot


class TestBotExternalSignal:
    """Bot.on_external_signal() 테스트."""

    async def test_reject_when_not_accepting(self) -> None:
        """accepts_external_signals=False 시 시그널 무시."""
        bot = _make_bot(_InhouseStrategy)

        event = ExternalSignalEvent(
            account_id="test",
            bot_id="bot-001",
            signal_id="sig-001",
            symbol="005930",
            action="buy",
            reason="test",
            confidence=0.9,
        )

        await bot.on_external_signal(event)

        # EventBus에 OrderRequestEvent 발행되지 않음
        bot._eventbus.publish.assert_not_called()

    async def test_accept_and_forward(self) -> None:
        """accepts_external_signals=True 시 on_data() 호출 및 시그널 발행."""
        bot = _make_bot(_OutsourcedStrategy)

        event = ExternalSignalEvent(
            account_id="test",
            bot_id="bot-001",
            signal_id="sig-001",
            symbol="005930",
            action="buy",
            reason="external signal",
            confidence=0.95,
        )

        await bot.on_external_signal(event)

        # on_data() → Signal → OrderRequestEvent 발행
        bot._eventbus.publish.assert_called_once()
        published = bot._eventbus.publish.call_args[0][0]
        assert published.symbol == "005930"
        assert published.side == "buy"

    async def test_ignore_wrong_bot_id(self) -> None:
        """다른 봇의 시그널은 무시."""
        bot = _make_bot(_OutsourcedStrategy)

        event = ExternalSignalEvent(
            account_id="test",
            bot_id="bot-999",  # 다른 봇
            signal_id="sig-001",
            symbol="005930",
            action="buy",
        )

        await bot.on_external_signal(event)
        bot._eventbus.publish.assert_not_called()

    async def test_ignore_non_event(self) -> None:
        """ExternalSignalEvent가 아닌 이벤트 무시."""
        bot = _make_bot(_OutsourcedStrategy)
        await bot.on_external_signal("not an event")
        bot._eventbus.publish.assert_not_called()

    async def test_ignore_when_no_strategy(self) -> None:
        """전략이 없을 때 무시."""
        bot = _make_bot(_OutsourcedStrategy)
        bot.strategy = None

        event = ExternalSignalEvent(
            account_id="test",
            bot_id="bot-001",
            signal_id="sig-001",
            symbol="005930",
            action="buy",
        )

        await bot.on_external_signal(event)
        bot._eventbus.publish.assert_not_called()


# ── #2146: ExternalSignalEvent account-scoped marker ────────


class TestExternalSignalAccountScoped:
    """#2146: ExternalSignalEvent 가 account-scoped marker 를 갖는지 검증."""

    def test_requires_account_id_marker(self) -> None:
        """_requires_account_id marker 가 True 다."""
        assert ExternalSignalEvent._requires_account_id is True
        assert "account_id" in ExternalSignalEvent.__dataclass_fields__

    def test_valid_account_id_constructs(self) -> None:
        """valid account_id 면 정상 생성된다."""
        event = ExternalSignalEvent(
            account_id="acc-test",
            bot_id="bot-001",
            signal_id="sig-001",
            symbol="005930",
            action="buy",
        )
        assert event.account_id == "acc-test"

    @pytest.mark.parametrize("invalid", [None, "", "default"])
    def test_invalid_account_id_raises(self, invalid: str | None) -> None:
        """invalid account_id(None/""/"default") 면 InvalidAccountIdError raise."""
        with pytest.raises(InvalidAccountIdError):
            ExternalSignalEvent(
                account_id=invalid,  # type: ignore[arg-type]
                bot_id="bot-001",
                signal_id="sig-001",
                symbol="005930",
                action="buy",
            )
