"""AccountService.delete() 이벤트 발행 테스트 (#717)."""

import pytest
import pytest_asyncio

from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountDeletedEvent,
    AccountSuspendedEvent,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 인메모리 DB."""
    db_path = str(tmp_path / "test_account_delete.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    """테스트용 EventBus."""
    return EventBus()


@pytest_asyncio.fixture
async def service(db, eventbus):
    """초기화된 AccountService."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    return svc


def _make_account(
    account_id: str = "test",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    **kwargs,
) -> Account:
    """테스트용 Account 생성 헬퍼."""
    return Account(
        account_id=account_id,
        name=name,
        exchange=exchange,
        currency=currency,
        broker_type=broker_type,
        **kwargs,
    )


class TestAccountDeleteEvents:
    """AccountService.delete() 이벤트 발행 테스트."""

    @pytest.mark.asyncio
    async def test_delete_publishes_events(self, service, eventbus):
        """delete()가 AccountSuspendedEvent -> AccountDeletedEvent 순서로 발행."""
        await service.create(_make_account())

        published: list = []

        async def on_suspended(event: AccountSuspendedEvent) -> None:
            published.append(("suspended", event))

        async def on_deleted(event: AccountDeletedEvent) -> None:
            published.append(("deleted", event))

        eventbus.subscribe(AccountSuspendedEvent, on_suspended)
        eventbus.subscribe(AccountDeletedEvent, on_deleted)

        await service.delete("test", deleted_by="admin")

        assert len(published) == 2

        # 순서 검증: suspended -> deleted
        assert published[0][0] == "suspended"
        assert published[0][1].account_id == "test"
        assert published[0][1].reason == "Account deletion"
        assert published[0][1].suspended_by == "admin"

        assert published[1][0] == "deleted"
        assert published[1][1].account_id == "test"
        assert published[1][1].deleted_by == "admin"

    @pytest.mark.asyncio
    async def test_delete_already_suspended_skips_suspend_event(
        self, service, eventbus
    ):
        """이미 SUSPENDED인 계좌 삭제 시 SuspendedEvent 미발행."""
        await service.create(_make_account())
        await service.suspend("test", reason="test reason", suspended_by="system")

        published: list = []

        async def on_suspended(event: AccountSuspendedEvent) -> None:
            published.append(("suspended", event))

        async def on_deleted(event: AccountDeletedEvent) -> None:
            published.append(("deleted", event))

        eventbus.subscribe(AccountSuspendedEvent, on_suspended)
        eventbus.subscribe(AccountDeletedEvent, on_deleted)

        await service.delete("test", deleted_by="admin")

        # AccountSuspendedEvent는 발행되지 않아야 함
        assert len(published) == 1
        assert published[0][0] == "deleted"
        assert published[0][1].account_id == "test"
        assert published[0][1].deleted_by == "admin"

    @pytest.mark.asyncio
    async def test_delete_sets_status_and_clears_cache(self, service):
        """delete() 후 상태가 DELETED로 변경되고 메모리 캐시에서 제거."""
        await service.create(_make_account())
        await service.delete("test", deleted_by="admin")

        # 메모리 캐시에서 제거됨
        assert "test" not in service._accounts

        # DB에서 DELETED 상태로 조회 가능
        account = await service.get("test")
        assert account.status == AccountStatus.DELETED
