"""AccountService.delete() 이벤트 발행 테스트 (#717, #1139).

#1139로 `AccountDeletedEvent`는 1.0 EventBus 계약에서 제거되었다.
cold-path delete는 consumer wiring을 트리거하지 않으며, 같은 모듈에서
발행되던 `AccountSuspendedEvent`(소속 봇 중지 트리거) 동작만 회귀 검증한다.
"""

import pytest
import pytest_asyncio

from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import AccountSuspendedEvent


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
    account_id: str = "main",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    **kwargs,
) -> Account:
    """테스트용 Account 생성 헬퍼."""
    if "credentials" not in kwargs:
        kwargs["credentials"] = {"app_key": "test", "app_secret": "test"}
    return Account(
        account_id=account_id,
        name=name,
        exchange=exchange,
        currency=currency,
        broker_type=broker_type,
        **kwargs,
    )


def test_account_deleted_event_is_not_part_of_runtime_contract():
    """AccountDeletedEvent는 1.0 EventBus 계약에서 제거되었다.

    회귀 가드: 향후 누군가 다시 정의하더라도 이 직접 단언이 fail하여
    cold-path consumer wiring 트리거 변경이 곧바로 노출된다.
    """
    import ante.eventbus.events as events_module

    assert not hasattr(events_module, "AccountDeletedEvent"), (
        "AccountDeletedEvent는 #1139에서 1.0 비계약으로 분류되었다. "
        "cold-path delete는 consumer wiring을 트리거하지 않으므로 "
        "이 이벤트를 다시 도입하지 말 것."
    )


class TestAccountDeleteEvents:
    """AccountService.delete() 이벤트 발행 테스트."""

    @pytest.mark.asyncio
    async def test_delete_publishes_suspend_only(self, service, eventbus):
        """delete()는 AccountSuspendedEvent만 발행한다.

        AccountDeletedEvent는 1.0 비계약이므로 발행되지 않는다.
        AccountSuspendedEvent(reason="Account deletion")는 BotManager가 소속
        봇을 중지시키도록 유지된다.
        """
        await service.create(_make_account())

        published: list = []

        async def on_suspended(event: AccountSuspendedEvent) -> None:
            published.append(("suspended", event))

        eventbus.subscribe(AccountSuspendedEvent, on_suspended)

        await service.delete("main", deleted_by="admin")

        assert len(published) == 1
        assert published[0][0] == "suspended"
        assert published[0][1].account_id == "main"
        assert published[0][1].reason == "Account deletion"
        assert published[0][1].suspended_by == "admin"

    @pytest.mark.asyncio
    async def test_delete_already_suspended_skips_suspend_event(
        self, service, eventbus
    ):
        """이미 SUSPENDED인 계좌 삭제 시 SuspendedEvent 미발행."""
        await service.create(_make_account())
        await service.suspend("main", reason="test reason", suspended_by="system")

        published: list = []

        async def on_suspended(event: AccountSuspendedEvent) -> None:
            published.append(("suspended", event))

        eventbus.subscribe(AccountSuspendedEvent, on_suspended)

        await service.delete("main", deleted_by="admin")

        # AccountSuspendedEvent는 새로 발행되지 않아야 함
        # (이미 suspend 시 1회 발행되었지만 delete()에서는 추가 발행 없음)
        assert len(published) == 0

    @pytest.mark.asyncio
    async def test_delete_sets_status_and_clears_cache(self, service):
        """delete() 후 상태가 DELETED로 변경되고 메모리 캐시에서 제거."""
        await service.create(_make_account())
        await service.delete("main", deleted_by="admin")

        # 메모리 캐시에서 제거됨
        assert "main" not in service._accounts

        # DB에서 DELETED 상태로 조회 가능
        account = await service.get("main")
        assert account.status == AccountStatus.DELETED
