"""가상 동기화가 유한한 실수가 아닌 시세를 조회 실패로 본다 (#3135).

스펙: `docs/specs/treasury/09-virtual-asset-sync.md`의 fallback 문단,
`04-treasury-interface.md` 「동기화 시세 (#3103)」.

실제 Treasury·Database·PositionHistory를 쓰고 시세 조회기만 가짜로 둔다.
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

import ante.treasury.treasury as treasury_module
from ante.core import Database, clock
from ante.eventbus import EventBus
from ante.eventbus.events import BalanceSyncedEvent
from ante.trade.position import PositionHistory
from ante.treasury import Treasury
from tests.unit.test_rule_engine_holdings_price_3102 import (
    _H,
    PREFIX,
    _Clock,
)

_ACCOUNT = "acc-3135"
_INTERVAL = 300
_QTY = 10.0
_AVG = 1000.0
_GOOD = 1100.0
_EXPECTED_EVAL = _GOOD * _QTY + _AVG * _QTY
_RAISE = object()

_BAD_VALUES = [
    pytest.param(None, id="none"),
    pytest.param("1200", id="str"),
    pytest.param(True, id="bool"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="-inf"),
    pytest.param(10**400, id="huge-int"),
    pytest.param(_RAISE, id="raises"),
]


class _Resolver:
    def __init__(self, prices: dict[str, Any]) -> None:
        self.prices = prices
        self.calls: list[str] = []

    async def __call__(self, symbol: str) -> Any:
        self.calls.append(symbol)
        value = self.prices[symbol]
        if value is _RAISE:
            raise RuntimeError(f"no quote for {symbol}")
        return value


class _Stack:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.history = PositionHistory(db)
        self.treasury = Treasury(db=db, eventbus=self.bus, account_id=_ACCOUNT)
        self.synced: list[BalanceSyncedEvent] = []

    async def start(self, symbols: list[str], quantity: float = _QTY) -> None:
        await self.history.initialize()
        await self.treasury.initialize()
        for symbol in symbols:
            await self.history.force_update(
                "bot1", symbol, quantity, _AVG, account_id=_ACCOUNT
            )
        self.bus.subscribe(BalanceSyncedEvent, self.synced.append)
        self.treasury.start_sync(
            None,
            self.history,
            interval_seconds=_INTERVAL,
            trading_mode="virtual",
        )
        await self.treasury.stop_sync()

    async def sync(self, resolver: _Resolver) -> None:
        await self.treasury._do_sync_virtual(self.history, resolver)  # type: ignore[arg-type]

    async def stored_eval(self) -> Any:
        row = await self.db.fetch_one(
            "SELECT eval_amount FROM treasury_state WHERE account_id = ?",
            (_ACCOUNT,),
        )
        return None if row is None else row["eval_amount"]

    async def snapshot_total(self) -> float:
        await self.treasury.save_daily_snapshot("2026-01-02")
        snap = await self.treasury.get_daily_snapshot("2026-01-02")
        assert snap is not None
        return float(snap["total_asset"])


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "bad-quote.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def stack(manual_clock: Any, db: Database) -> _Stack:
    return _Stack(db)


def _missing() -> tuple[None, str]:
    return None, treasury_module.SYNCED_PRICE_MISSING


class TestPredicate:
    @pytest.mark.parametrize(
        "value",
        [0, 0.0, -1, -1.0, 1, 1.5, 10**300, sys.float_info.max],
    )
    def test_finite_numbers_pass(self, value: Any) -> None:
        assert treasury_module._is_finite_number(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "1200",
            True,
            False,
            float("nan"),
            float("inf"),
            float("-inf"),
            10**400,
            -(10**400),
            [1.0],
        ],
    )
    def test_non_finite_or_non_numbers_fail(self, value: Any) -> None:
        assert treasury_module._is_finite_number(value) is False


class TestBadQuoteIsLikeFailedQuote:
    @pytest.mark.parametrize("bad", _BAD_VALUES)
    @pytest.mark.parametrize("bad_first", [True, False], ids=["bad-first", "bad-last"])
    async def test_round_succeeds_and_bad_symbol_uses_average(
        self, stack: _Stack, bad: Any, bad_first: bool
    ) -> None:
        bad_symbol, good_symbol = ("AAA", "BBB") if bad_first else ("BBB", "AAA")
        await stack.start(["AAA", "BBB"])
        resolver = _Resolver({bad_symbol: bad, good_symbol: _GOOD})

        await stack.sync(resolver)

        assert resolver.calls == ["AAA", "BBB"]
        treasury = stack.treasury
        assert treasury._eval_amount == _EXPECTED_EVAL
        assert treasury._purchase_amount == _AVG * _QTY * 2
        assert treasury.get_synced_price(good_symbol) == (_GOOD, None)
        assert treasury.get_synced_price(bad_symbol) == _missing()
        coverage = treasury.get_last_sync_coverage()
        assert coverage is not None
        assert coverage[1] == frozenset({"AAA", "BBB"})
        assert len(stack.synced) == 1
        summary = treasury.get_summary()
        assert summary["eval_amount"] == _EXPECTED_EVAL
        assert math.isfinite(summary["ante_eval_amount"])
        assert await stack.stored_eval() == _EXPECTED_EVAL
        assert math.isfinite(await stack.snapshot_total())

    @pytest.mark.parametrize("bad", _BAD_VALUES)
    async def test_old_price_is_kept_and_goes_stale(
        self, stack: _Stack, manual_clock: Any, bad: Any
    ) -> None:
        await stack.start(["AAA"])
        resolver = _Resolver({"AAA": _GOOD})
        await stack.sync(resolver)

        resolver.prices["AAA"] = bad
        manual_clock.advance(_INTERVAL)
        await stack.sync(resolver)

        assert stack.treasury._eval_amount == _AVG * _QTY
        assert stack.treasury.get_synced_price("AAA") == (_GOOD, None)
        assert len(stack.synced) == 2
        manual_clock.advance(_INTERVAL + 1)
        assert stack.treasury.get_synced_price("AAA") == (
            None,
            treasury_module.SYNCED_PRICE_STALE,
        )


class TestZeroAndNegativeUnchanged:
    @pytest.mark.parametrize("value", [0, 0.0, -1.0])
    async def test_value_is_used_as_is_and_not_recorded(
        self, stack: _Stack, value: Any
    ) -> None:
        await stack.start(["AAA", "BBB"])
        resolver = _Resolver({"AAA": value, "BBB": _GOOD})

        await stack.sync(resolver)

        assert stack.treasury._eval_amount == value * _QTY + _GOOD * _QTY
        assert stack.treasury.get_synced_price("AAA") == _missing()
        assert stack.treasury.get_synced_price("BBB") == (_GOOD, None)
        coverage = stack.treasury.get_last_sync_coverage()
        assert coverage is not None
        assert coverage[1] == frozenset({"AAA", "BBB"})


class TestTotalOverflowFailsRound:
    async def test_finite_price_times_quantity_overflow_keeps_previous(
        self, stack: _Stack, manual_clock: Any
    ) -> None:
        await stack.start(["AAA", "BBB"])
        await stack.sync(_Resolver({"AAA": _GOOD, "BBB": _GOOD}))
        before_coverage = stack.treasury.get_last_sync_coverage()
        before_synced_at = stack.treasury._last_synced_at
        assert stack.treasury._eval_amount == _GOOD * _QTY * 2

        manual_clock.advance(60)
        with pytest.raises(ValueError):
            await stack.sync(_Resolver({"AAA": 1e308, "BBB": _GOOD}))

        assert stack.treasury._eval_amount == _GOOD * _QTY * 2
        assert stack.treasury._last_synced_at == before_synced_at
        assert stack.treasury.get_last_sync_coverage() == before_coverage
        assert len(stack.synced) == 1
        assert await stack.stored_eval() == _GOOD * _QTY * 2
        assert math.isfinite(await stack.snapshot_total())

    async def test_purchase_total_overflow_fails_round(self, stack: _Stack) -> None:
        await stack.start(["AAA"], quantity=1e308)
        stack.treasury._eval_amount = 5.0

        with pytest.raises(ValueError):
            await stack.sync(_Resolver({"AAA": 0.0}))

        assert stack.treasury._eval_amount == 5.0
        assert stack.treasury._last_synced_at is None
        assert stack.synced == []
        assert await stack.stored_eval() is None


@pytest.fixture
def clk() -> Any:
    manual = _Clock(datetime(2026, 1, 2, 3, 0, 0, tzinfo=UTC))
    with clock.use_clock(manual):
        yield manual


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), 10**400])
async def test_bad_quote_symbol_blocks_buy_under_unrealized_loss_limit(
    db: Database, clk: _Clock, bad: Any
) -> None:
    h = _H(db, clk, live=False)
    await h.start()
    a, b, c = "005930", "000660", "035420"
    await h.fill(a, 10, 60_000.0)
    await h.fill(b, 10, 60_000.0)
    await h.sync({a: 60_000.0, b: bad})
    h.ul(0.05)

    await h.order(c)

    assert h.validated == []
    assert h.reasons() == [f"{PREFIX}: {b}: {treasury_module.SYNCED_PRICE_MISSING}"]
    coverage = h.treasury.get_last_sync_coverage()
    assert coverage is not None
    assert b in coverage[1]
