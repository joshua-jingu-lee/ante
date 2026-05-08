"""TreasuryManager 단위 테스트."""

from decimal import Decimal

import pytest

from ante.account.models import Account
from ante.core import Database
from ante.eventbus import EventBus
from ante.treasury import TreasuryManager

# -- Fixtures -------------------------------------------------


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def domestic_account():
    return Account(
        account_id="domestic",
        name="국내주식",
        exchange="KRX",
        currency="KRW",
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


@pytest.fixture
def us_account():
    return Account(
        account_id="us-stock",
        name="미국주식",
        exchange="NASDAQ",
        currency="USD",
        buy_commission_rate=Decimal("0.001"),
        sell_commission_rate=Decimal("0.001"),
    )


@pytest.fixture
async def manager(db, eventbus):
    return TreasuryManager(db=db, eventbus=eventbus)


# -- TreasuryManager 테스트 ----------------------------------


class TestTreasuryManager:
    async def test_create_treasury(self, manager, domestic_account):
        """create_treasury로 Treasury 인스턴스 생성."""
        treasury = await manager.create_treasury(domestic_account)

        assert treasury.account_id == "domestic"
        assert treasury.currency == "KRW"
        assert treasury.buy_commission_rate == pytest.approx(0.00015)
        assert treasury.sell_commission_rate == pytest.approx(0.00195)

    async def test_get(self, manager, domestic_account):
        """get으로 Treasury 인스턴스 조회."""
        await manager.create_treasury(domestic_account)
        treasury = manager.get("domestic")
        assert treasury.account_id == "domestic"

    async def test_get_not_found(self, manager):
        """존재하지 않는 계좌 조회 시 KeyError."""
        with pytest.raises(KeyError, match="nonexistent"):
            manager.get("nonexistent")

    async def test_list_all(self, manager, domestic_account, us_account):
        """list_all로 전체 Treasury 목록 조회."""
        await manager.create_treasury(domestic_account)
        await manager.create_treasury(us_account)

        treasuries = manager.list_all()
        assert len(treasuries) == 2
        ids = {t.account_id for t in treasuries}
        assert ids == {"domestic", "us-stock"}

    async def test_initialize_all(self, manager, domestic_account, us_account):
        """initialize_all로 여러 계좌의 Treasury 일괄 생성."""
        await manager.initialize_all([domestic_account, us_account])

        treasuries = manager.list_all()
        assert len(treasuries) == 2

        domestic = manager.get("domestic")
        assert domestic.currency == "KRW"

        us = manager.get("us-stock")
        assert us.currency == "USD"

    async def test_get_total_summary(self, manager, domestic_account, us_account):
        """get_total_summary로 전 계좌 합산 요약."""
        await manager.initialize_all([domestic_account, us_account])

        domestic = manager.get("domestic")
        await domestic.set_account_balance(10_000_000.0)

        us = manager.get("us-stock")
        await us.set_account_balance(5_000.0)

        summary = await manager.get_total_summary()
        assert "accounts" in summary
        assert len(summary["accounts"]) == 2

        accounts_by_id = {a["account_id"]: a for a in summary["accounts"]}
        assert accounts_by_id["domestic"]["currency"] == "KRW"
        assert accounts_by_id["us-stock"]["currency"] == "USD"

    async def test_separate_treasury_isolation(
        self, manager, domestic_account, us_account
    ):
        """각 계좌의 Treasury는 독립적으로 동작한다."""
        await manager.initialize_all([domestic_account, us_account])

        domestic = manager.get("domestic")
        await domestic.set_account_balance(10_000_000.0)
        await domestic.allocate("bot1", 3_000_000.0)

        us = manager.get("us-stock")
        await us.set_account_balance(5_000.0)
        await us.allocate("bot2", 2_000.0)

        # 각자의 봇만 관리
        assert domestic.get_budget("bot1") is not None
        assert domestic.get_budget("bot2") is None

        assert us.get_budget("bot2") is not None
        assert us.get_budget("bot1") is None

        # 잔액 독립
        assert domestic.unallocated == 7_000_000.0
        assert us.unallocated == 3_000.0


# -- #1333: market_order_reserve_buffer_rate / resolver wiring -----


class TestTreasuryManagerMarketBufferAndResolver:
    """TreasuryManager 가 Account.market_order_reserve_buffer_rate 를 Treasury 에
    전달하고, ``set_order_reserve_price_resolver`` 로 후속 resolver 주입을
    지원하는지 검증한다 (#1333).
    """

    async def test_buffer_passed_to_treasury(self, manager):
        """create_treasury 가 Account 의 buffer 값을 Treasury 에 그대로 주입."""
        account = Account(
            account_id="domestic",
            name="국내주식",
            exchange="KRX",
            currency="KRW",
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
            market_order_reserve_buffer_rate=Decimal("0.005"),
        )
        treasury = await manager.create_treasury(account)
        assert treasury._market_order_reserve_buffer_rate == Decimal("0.005")

    async def test_set_order_reserve_price_resolver_injects_into_treasury(
        self, manager, domestic_account
    ):
        """setter 가 Treasury 인스턴스에 resolver 를 주입한다."""
        await manager.create_treasury(domestic_account)

        async def my_resolver(symbol: str) -> float:
            return 12_345.0

        manager.set_order_reserve_price_resolver("domestic", my_resolver)
        treasury = manager.get("domestic")
        # 직접 호출로 주입 여부 검증.
        assert treasury._order_reserve_price_resolver is my_resolver

    async def test_set_order_reserve_price_resolver_unknown_account_keyerror(
        self, manager
    ):
        """등록되지 않은 계좌에 resolver 주입 시 KeyError."""

        async def r(symbol: str) -> float:
            return 0.0

        with pytest.raises(KeyError, match="nonexistent"):
            manager.set_order_reserve_price_resolver("nonexistent", r)

    async def test_main_style_wiring_closure_captures_correct_account_id(
        self, manager, domestic_account, us_account
    ):
        """main._init_gateway 의 closure 패턴이 계좌별로 account_id 를 정확히
        캡처해 APIGateway.get_current_price 에 전달한다 (#1333 wiring 회귀).

        late binding 회귀(``account_id`` 가 마지막 loop 값으로 고정되는 것)
        가 발생하면 두 계좌의 resolver 가 동일 account_id 로 호출되어 본
        테스트의 assertion 이 실패한다.
        """
        from collections.abc import Awaitable, Callable

        await manager.initialize_all([domestic_account, us_account])

        # Fake APIGateway: account_id 를 기록하고 deterministic price 반환.
        seen: dict[str, str] = {}

        class FakeGateway:
            async def get_current_price(self, symbol: str, *, account_id: str) -> float:
                seen[account_id] = symbol
                return 1_000.0

        gateway = FakeGateway()

        # main._init_gateway 의 closure 패턴 그대로 적용.
        for account in [domestic_account, us_account]:

            def _make_resolver(
                account_id: str,
            ) -> Callable[[str], Awaitable[float]]:
                async def _resolver(symbol: str) -> float:
                    return await gateway.get_current_price(
                        symbol, account_id=account_id
                    )

                return _resolver

            manager.set_order_reserve_price_resolver(
                account.account_id, _make_resolver(account.account_id)
            )

        # 각 Treasury 의 resolver 를 호출해서 account_id 캡처가 정확한지 확인.
        domestic_resolver = manager.get("domestic")._order_reserve_price_resolver
        us_resolver = manager.get("us-stock")._order_reserve_price_resolver
        assert domestic_resolver is not None
        assert us_resolver is not None

        await domestic_resolver("069500")
        await us_resolver("AAPL")

        # 각 resolver 가 자신의 account_id 로만 gateway 를 호출.
        assert seen == {"domestic": "069500", "us-stock": "AAPL"}
