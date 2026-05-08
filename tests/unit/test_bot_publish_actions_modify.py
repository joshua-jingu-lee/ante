"""Bot._publish_actions strategy_id 보강 테스트 (#1331).

본 모듈은 Bot이 ``OrderAction(action="cancel"|"modify")``을 EventBus
이벤트로 변환할 때 ``strategy_id`` 가 ``bot.config.strategy_id`` 로
정확히 채워지는지 검증한다. 이전 동작은 빈 문자열을 발행하여
룰/리포팅/외부 채널 단계에서 strategy 단위 식별이 불가능했다.

OrderAction 입력에 ``symbol`` / ``side`` 가 없으므로 본 PR 범위에서는
해당 필드를 보강하지 않는다 (Stop Conditions).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from ante.bot.bot import Bot
from ante.bot.config import BotConfig
from ante.eventbus.events import OrderCancelEvent, OrderModifyEvent
from ante.strategy.base import OrderAction


def _make_bot() -> Bot:
    config = BotConfig(
        bot_id="bot-1331",
        strategy_id="strat-1331",
        name="modify-test-bot",
        account_id="acc-1331",
        interval_seconds=60,
    )
    eventbus = MagicMock()
    eventbus.publish = AsyncMock()
    ctx = MagicMock()
    strategy_cls = MagicMock()
    return Bot(
        config=config,
        strategy_cls=strategy_cls,
        ctx=ctx,
        eventbus=eventbus,
    )


async def test_publish_actions_cancel_carries_strategy_id() -> None:
    """cancel 액션 → ``OrderCancelEvent.strategy_id`` 가 봇 설정과 일치."""
    bot = _make_bot()
    actions = [
        OrderAction(
            action="cancel",
            order_id="ord-cancel-1",
            reason="strategy decision",
        )
    ]

    await bot._publish_actions(actions)

    assert bot._eventbus.publish.await_count == 1
    published = bot._eventbus.publish.await_args_list[0].args[0]
    assert isinstance(published, OrderCancelEvent)
    assert published.strategy_id == "strat-1331"
    assert published.bot_id == "bot-1331"
    assert published.account_id == "acc-1331"
    assert published.order_id == "ord-cancel-1"
    assert published.reason == "strategy decision"


async def test_publish_actions_modify_carries_strategy_id() -> None:
    """modify 액션 → ``OrderModifyEvent.strategy_id`` 가 봇 설정과 일치."""
    bot = _make_bot()
    actions = [
        OrderAction(
            action="modify",
            order_id="ord-modify-1",
            quantity=5.0,
            price=51000.0,
            reason="price update",
        )
    ]

    await bot._publish_actions(actions)

    assert bot._eventbus.publish.await_count == 1
    published = bot._eventbus.publish.await_args_list[0].args[0]
    assert isinstance(published, OrderModifyEvent)
    assert published.strategy_id == "strat-1331"
    assert published.bot_id == "bot-1331"
    assert published.account_id == "acc-1331"
    assert published.order_id == "ord-modify-1"
    assert published.quantity == 5.0
    assert published.price == 51000.0
    assert published.reason == "price update"


async def test_publish_actions_mixed_preserve_strategy_id() -> None:
    """cancel + modify 혼합 시 두 이벤트 모두에 strategy_id 보존."""
    bot = _make_bot()
    actions = [
        OrderAction(action="cancel", order_id="c-1"),
        OrderAction(action="modify", order_id="m-1", quantity=1.0, price=100.0),
    ]

    await bot._publish_actions(actions)

    published_events = [call.args[0] for call in bot._eventbus.publish.await_args_list]
    assert len(published_events) == 2
    for evt in published_events:
        assert getattr(evt, "strategy_id") == "strat-1331"
