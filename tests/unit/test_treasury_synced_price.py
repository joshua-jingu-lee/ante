"""잔고 동기화가 받은 종목별 현재가를 받은 시각과 함께 내준다 (#3103).

실제 Treasury와 임시 DB를 쓰고 브로커·포지션 이력만 가짜로 둔다. 시계는
``manual_clock``으로 고정해 낡음 판정을 단조 값으로만 움직인다.
"""

from __future__ import annotations

from typing import Any

import pytest

import ante.treasury.treasury as treasury_module
from ante.core import Database
from ante.eventbus import EventBus
from ante.trade.models import PositionSnapshot
from ante.treasury import Treasury

_ACCOUNT = "acc-synced"
_INTERVAL = 300


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def treasury(manual_clock: Any, db: Database) -> Treasury:
    t = Treasury(db=db, eventbus=EventBus(), account_id=_ACCOUNT)
    await t.initialize()
    return t


class _Broker:
    def __init__(self, positions: list[dict[str, Any]]) -> None:
        self.positions = positions
        self.fail_balance = False
        self.fail_positions = False

    async def get_account_balance(self) -> dict[str, float]:
        if self.fail_balance:
            raise RuntimeError("balance down")
        return {"cash": 1_000_000.0, "total_assets": 1_000_000.0}

    async def get_buyable(self, symbol: str, **_: Any) -> dict[str, float]:
        return {"order_buyable_amount": 900_000.0}

    async def get_positions(self) -> list[dict[str, Any]]:
        if self.fail_positions:
            raise RuntimeError("positions down")
        return self.positions


class _History:
    def __init__(self, positions: list[PositionSnapshot] | None = None) -> None:
        self.positions = positions or []
        self.fail = False

    async def get_all_positions(
        self, *, account_id: str | None = None
    ) -> list[PositionSnapshot]:
        if self.fail:
            raise RuntimeError("trade db down")
        return list(self.positions)


class _Resolver:
    def __init__(self, prices: dict[str, Any]) -> None:
        self.prices = prices

    async def __call__(self, symbol: str) -> Any:
        if symbol not in self.prices:
            raise RuntimeError(f"no quote for {symbol}")
        return self.prices[symbol]


def _row(symbol: str, price: Any, quantity: float = 10.0) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "quantity": quantity,
        "avg_price": 1000.0,
        "current_price": price,
        "eval_amount": 0.0,
    }


def _snap(symbol: str, quantity: float = 10.0, avg: float = 1000.0) -> PositionSnapshot:
    return PositionSnapshot(
        bot_id="bot1",
        symbol=symbol,
        quantity=quantity,
        avg_entry_price=avg,
        account_id=_ACCOUNT,
    )


async def _start(t: Treasury, interval: Any = _INTERVAL, **kwargs: Any) -> None:
    t.start_sync(None, _History(), interval_seconds=interval, **kwargs)
    await t.stop_sync()


def _missing() -> tuple[None, str]:
    return None, treasury_module.SYNCED_PRICE_MISSING


def _stale() -> tuple[None, str]:
    return None, treasury_module.SYNCED_PRICE_STALE


class TestLiveSync:
    async def test_records_every_response_symbol_and_skips_bad_values(
        self, treasury: Treasury
    ) -> None:
        await _start(treasury)
        broker = _Broker(
            [
                _row("NONE", None),
                _row("TEXT", "abc"),
                _row("ZERO", 0),
                _row("NAN", float("nan")),
                _row("INF", float("inf")),
                _row("NEG", -5.0),
                _row("BOOL", True),
                _row("STR", "100"),
                _row("HUGE", 10**400),
                {"symbol": "NOKEY", "quantity": 1.0, "avg_price": 1.0},
                _row("005930", 71000.0),
                _row("000660", 120000),
            ]
        )
        history = _History([_snap("005930")])

        await treasury._do_sync(broker, history)  # type: ignore[arg-type]

        assert treasury._last_synced_at is not None
        assert treasury.get_synced_price("005930") == (71000.0, None)
        assert treasury.get_synced_price("000660") == (120000.0, None)
        for symbol in (
            "NONE",
            "TEXT",
            "ZERO",
            "NAN",
            "INF",
            "NEG",
            "BOOL",
            "STR",
            "HUGE",
        ):
            assert treasury.get_synced_price(symbol) == _missing(), symbol
        assert treasury.get_synced_price("NOKEY") == _missing()
        assert treasury.get_synced_price("UNSEEN") == _missing()


class TestVirtualSync:
    async def test_failed_quote_is_missing_and_avg_price_is_not_a_quote(
        self, treasury: Treasury
    ) -> None:
        await _start(treasury, trading_mode="virtual")
        history = _History([_snap("AAA", 10.0, 1000.0), _snap("BBB", 5.0, 2000.0)])
        resolver = _Resolver({"AAA": 1100.0})

        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (1100.0, None)
        assert treasury.get_synced_price("BBB") == _missing()
        assert treasury._eval_amount == 1100.0 * 10.0 + 2000.0 * 5.0
        assert treasury._purchase_amount == 1000.0 * 10.0 + 2000.0 * 5.0

    async def test_failed_quote_keeps_old_value_which_goes_stale(
        self, treasury: Treasury, manual_clock: Any
    ) -> None:
        await _start(treasury, trading_mode="virtual")
        history = _History([_snap("AAA", 10.0, 1000.0)])
        resolver = _Resolver({"AAA": 1100.0})
        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        resolver.prices.clear()
        manual_clock.advance(300)
        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        assert treasury._eval_amount == 1000.0 * 10.0
        assert treasury.get_synced_price("AAA") == (1100.0, None)
        manual_clock.advance(301)
        assert treasury.get_synced_price("AAA") == _stale()

    async def test_resolved_bad_value_is_not_recorded(self, treasury: Treasury) -> None:
        await _start(treasury, trading_mode="virtual")
        history = _History([_snap("AAA"), _snap("BBB")])
        resolver = _Resolver({"AAA": 0.0, "BBB": -1.0})

        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == _missing()
        assert treasury.get_synced_price("BBB") == _missing()

    async def test_no_resolver_records_nothing(self, treasury: Treasury) -> None:
        await _start(treasury, trading_mode="virtual")
        history = _History([_snap("AAA", 10.0, 1000.0)])

        await treasury._do_sync_virtual(history, None)

        assert treasury.get_synced_price("AAA") == _missing()
        assert treasury._eval_amount == 1000.0 * 10.0


class TestStaleness:
    async def test_fresh_at_exactly_twice_interval_and_stale_after(
        self, treasury: Treasury, manual_clock: Any
    ) -> None:
        await _start(treasury)
        await treasury._do_sync(_Broker([_row("AAA", 500.0)]), _History())  # type: ignore[arg-type]

        manual_clock.advance(2 * _INTERVAL)
        assert treasury.get_synced_price("AAA") == (500.0, None)
        manual_clock.advance(1)
        assert treasury.get_synced_price("AAA") == _stale()

    async def test_failed_sync_keeps_old_value_and_it_goes_stale(
        self, treasury: Treasury, manual_clock: Any
    ) -> None:
        await _start(treasury)
        broker = _Broker([_row("AAA", 500.0)])
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        broker.fail_balance = True
        manual_clock.advance(_INTERVAL)
        with pytest.raises(RuntimeError):
            await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (500.0, None)
        manual_clock.advance(_INTERVAL + 1)
        assert treasury.get_synced_price("AAA") == _stale()


class TestPrune:
    async def test_live_symbol_gone_from_response_is_removed(
        self, treasury: Treasury
    ) -> None:
        await _start(treasury)
        broker = _Broker([_row("AAA", 500.0), _row("BBB", 600.0)])
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        broker.positions = [_row("AAA", 510.0)]
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (510.0, None)
        assert treasury.get_synced_price("BBB") == _missing()

    async def test_live_failure_after_positions_does_not_prune(
        self, treasury: Treasury
    ) -> None:
        await _start(treasury)
        broker = _Broker([_row("AAA", 500.0), _row("BBB", 600.0)])
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        broker.positions = [_row("AAA", 510.0)]
        failing = _History()
        failing.fail = True
        with pytest.raises(RuntimeError):
            await treasury._do_sync(broker, failing)  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (510.0, None)
        assert treasury.get_synced_price("BBB") == (600.0, None)

    async def test_live_failed_positions_call_changes_nothing(
        self, treasury: Treasury
    ) -> None:
        await _start(treasury)
        broker = _Broker([_row("AAA", 500.0)])
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        broker.fail_positions = True
        with pytest.raises(RuntimeError):
            await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (500.0, None)

    async def test_virtual_closed_position_is_removed(self, treasury: Treasury) -> None:
        await _start(treasury, trading_mode="virtual")
        history = _History([_snap("AAA"), _snap("BBB")])
        resolver = _Resolver({"AAA": 1100.0, "BBB": 1200.0})
        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        history.positions = [_snap("AAA")]
        await treasury._do_sync_virtual(history, resolver)  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (1100.0, None)
        assert treasury.get_synced_price("BBB") == _missing()


class TestOverwrite:
    async def test_next_sync_replaces_value_and_time(
        self, treasury: Treasury, manual_clock: Any
    ) -> None:
        await _start(treasury)
        broker = _Broker([_row("AAA", 500.0)])
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        manual_clock.advance(500)
        broker.positions = [_row("AAA", 550.0)]
        await treasury._do_sync(broker, _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == (550.0, None)
        manual_clock.advance(500)
        assert treasury.get_synced_price("AAA") == (550.0, None)


class TestIntervalGuard:
    async def test_missing_before_start_sync(self, treasury: Treasury) -> None:
        await treasury._do_sync(_Broker([_row("AAA", 500.0)]), _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == _missing()

    @pytest.mark.parametrize(
        "interval", [0, -1, "300", True, float("nan"), float("inf"), None, 10**400]
    )
    async def test_bad_interval_is_always_missing(
        self, treasury: Treasury, interval: Any
    ) -> None:
        await _start(treasury, interval)
        await treasury._do_sync(_Broker([_row("AAA", 500.0)]), _History())  # type: ignore[arg-type]

        assert treasury.get_synced_price("AAA") == _missing()


class TestRestartGap:
    async def test_new_treasury_has_no_price_before_first_sync(
        self, treasury: Treasury, db: Database
    ) -> None:
        await _start(treasury)
        await treasury._do_sync(_Broker([_row("AAA", 500.0)]), _History())  # type: ignore[arg-type]
        assert treasury.get_synced_price("AAA") == (500.0, None)

        restarted = Treasury(db=db, eventbus=EventBus(), account_id=_ACCOUNT)
        await restarted.initialize()
        await _start(restarted)

        assert restarted.get_synced_price("AAA") == _missing()
