"""mock 브로커 타입을 계좌에 연결하는 경로 테스트."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from ante.account import service as account_service_module
from ante.account.errors import InvalidBrokerTypeError
from ante.account.models import Account, TradingMode
from ante.account.presets import BROKER_PRESETS, VIRTUAL_ONLY_BROKER_TYPES
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.account.service import AccountService
from ante.bot.providers.virtual import VirtualExecutor
from ante.broker.mock import MockBrokerAdapter
from ante.broker.registry import BROKER_REGISTRY
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import OrderApprovedEvent, OrderFailedEvent, OrderFilledEvent
from ante.gateway.gateway import APIGateway

ACCOUNT_ID = "scenario"


def _mock_account(
    prices_file: str,
    *,
    account_id: str = ACCOUNT_ID,
    trading_mode: TradingMode = TradingMode.VIRTUAL,
) -> Account:
    preset = BROKER_PRESETS["mock"]
    return Account(
        account_id=account_id,
        name="시나리오",
        exchange=preset.exchange,
        currency=preset.currency,
        timezone=preset.timezone,
        trading_hours_start=preset.trading_hours_start,
        trading_hours_end=preset.trading_hours_end,
        trading_mode=trading_mode,
        broker_type="mock",
        credentials={},
        broker_config={"prices_file": prices_file},
        buy_commission_rate=preset.buy_commission_rate,
        sell_commission_rate=preset.sell_commission_rate,
        market_order_reserve_buffer_rate=preset.market_order_reserve_buffer_rate,
    )


@pytest.fixture
def prices_file(tmp_path: Path) -> str:
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"prices": {"000001": 72000}, "default_price": 50000}),
        encoding="utf-8",
    )
    return str(path)


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "accounts.db"))
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def service(db: Database) -> AccountService:
    svc = AccountService(db, EventBus())
    await svc.initialize()
    return svc


def test_registry_and_preset_key_sets_match() -> None:
    """BROKER_REGISTRY, _BROKER_REGISTRY, BROKER_PRESETS의 키 집합이 같다."""
    account_service_module._register_brokers()
    service_keys = set(account_service_module._BROKER_REGISTRY)
    assert set(BROKER_REGISTRY) == service_keys == set(BROKER_PRESETS)
    assert "mock" in service_keys
    assert account_service_module._BROKER_REGISTRY["mock"] is MockBrokerAdapter


def test_virtual_only_broker_types_are_registered() -> None:
    """가상 전용 타입은 모두 등록된 브로커 타입이다."""
    assert "mock" in VIRTUAL_ONLY_BROKER_TYPES
    assert VIRTUAL_ONLY_BROKER_TYPES <= set(BROKER_PRESETS)


@pytest.mark.asyncio
async def test_create_virtual_mock_account_and_get_broker(
    service: AccountService, prices_file: str
) -> None:
    """mock 가상 계좌를 만들고 get_broker가 MockBrokerAdapter를 돌려준다."""
    created = await service.create(_mock_account(prices_file))
    assert created.broker_type == "mock"
    assert created.credentials == {}

    broker = await service.get_broker(ACCOUNT_ID)
    assert isinstance(broker, MockBrokerAdapter)
    assert broker.exchange == "TEST"
    assert await broker.get_current_price("000001") == 72000
    assert await broker.get_current_price("999999") == 50000


@pytest.mark.asyncio
async def test_create_live_mock_account_rejected(
    service: AccountService, prices_file: str
) -> None:
    """(mock, live) 계좌 생성은 InvalidBrokerTypeError다."""
    with pytest.raises(InvalidBrokerTypeError) as exc_info:
        await service.create(_mock_account(prices_file, trading_mode=TradingMode.LIVE))
    assert exc_info.value.code == "ACCOUNT_INVALID_BROKER_TYPE"
    assert "trading_mode" in str(exc_info.value)
    row = await service._db.fetch_one(
        "SELECT account_id FROM accounts WHERE account_id = ?", (ACCOUNT_ID,)
    )
    assert row is None


@pytest.mark.asyncio
async def test_seed_path_rejects_live_mock_account(
    service: AccountService, prices_file: str
) -> None:
    """seed 경로도 _persist_account를 거쳐 (mock, live)를 거부한다."""
    account = _mock_account(
        prices_file, account_id="mock", trading_mode=TradingMode.LIVE
    )
    with pytest.raises(InvalidBrokerTypeError):
        await service._create_seed_account(account)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broker_config",
    [{}, {"trading_mode": "virtual"}],
    ids=["plain", "broker-config-trading-mode-virtual"],
)
async def test_get_broker_rejects_live_mock_row_written_directly(
    db: Database,
    service: AccountService,
    prices_file: str,
    broker_config: dict[str, Any],
) -> None:
    """DB 행을 직접 (mock, live)로 고치면 get_broker가 InvalidBrokerTypeError다."""
    await service.create(_mock_account(prices_file))
    await db.execute(
        "UPDATE accounts SET trading_mode = 'live', broker_config = ? "
        "WHERE account_id = ?",
        (json.dumps({"prices_file": prices_file, **broker_config}), ACCOUNT_ID),
    )
    reloaded = AccountService(db, EventBus())
    await reloaded.initialize()
    assert (await reloaded.get(ACCOUNT_ID)).trading_mode == TradingMode.LIVE

    with pytest.raises(InvalidBrokerTypeError) as exc_info:
        await reloaded.get_broker(ACCOUNT_ID)
    assert exc_info.value.code == "ACCOUNT_INVALID_BROKER_TYPE"


_FILL_FIELDS = ("symbol", "side", "quantity", "price", "commission")


async def _run_market_orders(tmp_path: Path, prices_file: str) -> list[tuple]:
    database = Database(str(tmp_path / "accounts.db"))
    await database.connect()
    try:
        bus = EventBus()
        svc = AccountService(database, bus)
        await svc.initialize()
        await svc.create(_mock_account(prices_file))

        registry = RuntimeReadinessRegistry()
        registry.mark_ready(ACCOUNT_ID, ReadinessFlag.TREASURY_SYNC)
        gateway = APIGateway(account_service=svc, eventbus=bus)
        executor = VirtualExecutor(
            eventbus=bus,
            gateway=gateway,
            runtime_readiness=registry,
            account_service=svc,
        )
        executor.register_bot("bot1")
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        failed: list[OrderFailedEvent] = []
        bus.subscribe(OrderFilledEvent, filled.append)
        bus.subscribe(OrderFailedEvent, failed.append)

        for order_id, side, quantity in (
            ("o-buy", "buy", 10.0),
            ("o-sell", "sell", 4.0),
        ):
            await bus.publish(
                OrderApprovedEvent(
                    order_id=order_id,
                    account_id=ACCOUNT_ID,
                    bot_id="bot1",
                    strategy_id="s1",
                    symbol="000001",
                    side=side,
                    quantity=quantity,
                    order_type="market",
                    exchange="TEST",
                )
            )

        assert failed == []
        return [tuple(getattr(e, f) for f in _FILL_FIELDS) for e in filled]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_virtual_fills_are_deterministic_across_runs(
    tmp_path: Path, prices_file: str
) -> None:
    """같은 가격 파일로 새로 조립한 두 실행의 체결 필드가 같다."""
    first_dir = tmp_path / "run1"
    second_dir = tmp_path / "run2"
    first_dir.mkdir()
    second_dir.mkdir()

    first = await _run_market_orders(first_dir, prices_file)
    second = await _run_market_orders(second_dir, prices_file)

    assert first == second
    assert [(s, side, q, p) for s, side, q, p, _ in first] == [
        ("000001", "buy", 10.0, 72000),
        ("000001", "sell", 4.0, 72000),
    ]
    assert first[0][4] == pytest.approx(72000 * 10 * 0.00015)
    assert first[1][4] == pytest.approx(72000 * 4 * (0.00015 + 0.0023))
