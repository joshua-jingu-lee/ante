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
