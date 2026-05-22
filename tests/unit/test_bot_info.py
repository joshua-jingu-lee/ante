"""``ante.bot.info.enrich_bot_info`` 검증 (#1712).

검증 대상:
- 모든 의존성 부재 시 ``bot.get_info()`` 결과를 그대로 반환(보강 키 부재).
- 의존성별 보강 키 추가:
  - ``strategy_registry`` → ``strategy_name`` / ``strategy_author_*`` / ``strategy``
  - ``treasury`` (단일 인스턴스) → ``budget`` (allocated/spent/reserved/available)
  - ``trade_service`` → ``positions`` (symbol/quantity/avg_entry_price/realized_pnl)
- 응답 shape/field 가 Web API ``GET /api/bots/{bot_id}`` 라우트와 정렬
  (behavior-preserving extraction 회귀 lock).
- ``trade_service=None`` (legacy ServiceRegistry / cold-path) 시 ``positions``
  키 부재 — 빈 리스트로 흡수되는 contract drift 차단.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ante.bot.info import enrich_bot_info


def _make_bot(
    *,
    bot_id: str = "bot-1",
    info: dict | None = None,
) -> SimpleNamespace:
    base = (
        info
        if info is not None
        else {
            "bot_id": bot_id,
            "status": "running",
            "strategy_id": "",
        }
    )
    return SimpleNamespace(bot_id=bot_id, get_info=MagicMock(return_value=base))


class TestEnrichBotInfo:
    async def test_no_dependencies_returns_base_info_only(self) -> None:
        """의존성 모두 None → ``bot.get_info()`` 결과를 그대로 반환."""
        bot = _make_bot(info={"bot_id": "bot-1", "status": "running"})
        info = await enrich_bot_info(bot)

        assert info == {"bot_id": "bot-1", "status": "running"}

    async def test_strategy_registry_adds_strategy_keys(self) -> None:
        """``strategy_registry`` 가 record 반환 → strategy 보강 4 키 추가."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": "strat-1"})
        record = SimpleNamespace(
            name="MyStrategy",
            version="1.2",
            author_name="alice",
            author_id="ag-alice",
            description="my desc",
        )
        registry = MagicMock()
        registry.get = AsyncMock(return_value=record)

        info = await enrich_bot_info(bot, strategy_registry=registry)

        assert info["strategy_name"] == "MyStrategy"
        assert info["strategy_author_name"] == "alice"
        assert info["strategy_author_id"] == "ag-alice"
        assert info["strategy"] == {
            "name": "MyStrategy",
            "version": "1.2",
            "author_name": "alice",
            "author_id": "ag-alice",
            "description": "my desc",
        }
        registry.get.assert_awaited_once_with("strat-1")

    async def test_strategy_registry_returns_none_omits_keys(self) -> None:
        """``strategy_registry.get`` → None 이면 strategy 키 부재."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": "strat-missing"})
        registry = MagicMock()
        registry.get = AsyncMock(return_value=None)

        info = await enrich_bot_info(bot, strategy_registry=registry)

        assert "strategy_name" not in info
        assert "strategy" not in info

    async def test_treasury_adds_budget(self) -> None:
        """``treasury.get_budget`` 가 BotBudget 반환 → budget 키 추가."""
        bot = _make_bot()
        budget = SimpleNamespace(
            allocated=10000.0,
            spent=2000.0,
            reserved=500.0,
            available=7500.0,
        )
        treasury = MagicMock()
        treasury.get_budget = MagicMock(return_value=budget)

        info = await enrich_bot_info(bot, treasury=treasury)

        assert info["budget"] == {
            "allocated": 10000.0,
            "spent": 2000.0,
            "reserved": 500.0,
            "available": 7500.0,
        }
        treasury.get_budget.assert_called_once_with("bot-1")

    async def test_treasury_returns_none_omits_budget(self) -> None:
        """``treasury.get_budget`` → None 이면 budget 키 부재."""
        bot = _make_bot()
        treasury = MagicMock()
        treasury.get_budget = MagicMock(return_value=None)

        info = await enrich_bot_info(bot, treasury=treasury)

        assert "budget" not in info

    async def test_trade_service_adds_positions(self) -> None:
        """``trade_service.get_positions`` 결과를 positions 키로 보강."""
        bot = _make_bot()
        position = SimpleNamespace(
            symbol="005930",
            quantity=10,
            avg_entry_price=70000.0,
            realized_pnl=1500.0,
        )
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[position])

        info = await enrich_bot_info(bot, trade_service=trade_service)

        assert info["positions"] == [
            {
                "symbol": "005930",
                "quantity": 10,
                "avg_entry_price": 70000.0,
                "realized_pnl": 1500.0,
            }
        ]
        trade_service.get_positions.assert_awaited_once_with(
            bot_id="bot-1", include_closed=True
        )

    async def test_trade_service_none_omits_positions(self) -> None:
        """#1712 회귀 lock: ``trade_service=None`` 시 positions 키 부재.

        legacy ServiceRegistry 호환 — 빈 리스트로 흡수되는 contract drift 차단.
        """
        bot = _make_bot()
        info = await enrich_bot_info(bot, trade_service=None)

        assert "positions" not in info

    async def test_trade_service_empty_positions_returns_empty_list(self) -> None:
        """``trade_service.get_positions`` → 빈 리스트면 positions=[] 키 존재."""
        bot = _make_bot()
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])

        info = await enrich_bot_info(bot, trade_service=trade_service)

        # positions 키는 존재(빈 리스트). 위 ``test_trade_service_none_omits_positions``
        # 와 명확히 구분된다 — None 의존성 vs. 의존성 있지만 결과 빈 리스트.
        assert info["positions"] == []

    async def test_all_dependencies_compose_into_full_envelope(self) -> None:
        """3 의존성 모두 주입 → strategy/budget/positions 모두 보강."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": "strat-1"})

        record = SimpleNamespace(
            name="S",
            version="1",
            author_name="a",
            author_id="ag-a",
            description="d",
        )
        registry = MagicMock()
        registry.get = AsyncMock(return_value=record)

        budget = SimpleNamespace(
            allocated=100.0, spent=10.0, reserved=5.0, available=85.0
        )
        treasury = MagicMock()
        treasury.get_budget = MagicMock(return_value=budget)

        position = SimpleNamespace(
            symbol="005930", quantity=1, avg_entry_price=1.0, realized_pnl=0.0
        )
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[position])

        info = await enrich_bot_info(
            bot,
            strategy_registry=registry,
            treasury=treasury,
            trade_service=trade_service,
        )

        assert info["strategy_name"] == "S"
        assert info["budget"]["allocated"] == 100.0
        assert info["positions"][0]["symbol"] == "005930"
