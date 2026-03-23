"""Account 불변 필드 수정 차단 테스트."""

import pytest
import pytest_asyncio

from ante.account.errors import AccountImmutableFieldError
from ante.account.models import Account, TradingMode
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 인메모리 DB."""
    db_path = str(tmp_path / "test_immutable.db")
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


def _make_account(account_id: str = "test") -> Account:
    return Account(
        account_id=account_id,
        name="테스트",
        exchange="TEST",
        currency="KRW",
        broker_type="test",
        credentials={"app_key": "test", "app_secret": "test"},
    )


# ── 불변 필드 수정 차단 ──────────────────────────────


@pytest.mark.asyncio
async def test_update_immutable_exchange_raises(service):
    """exchange 수정 시도 시 AccountImmutableFieldError 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError, match="exchange"):
        await service.update("test", exchange="NYSE")


@pytest.mark.asyncio
async def test_update_immutable_currency_raises(service):
    """currency 수정 시도 시 AccountImmutableFieldError 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError, match="currency"):
        await service.update("test", currency="USD")


@pytest.mark.asyncio
async def test_update_immutable_trading_mode_raises(service):
    """trading_mode 수정 시도 시 AccountImmutableFieldError 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError, match="trading_mode"):
        await service.update("test", trading_mode=TradingMode.LIVE)


@pytest.mark.asyncio
async def test_update_immutable_broker_type_raises(service):
    """broker_type 수정 시도 시 AccountImmutableFieldError 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError, match="broker_type"):
        await service.update("test", broker_type="kis-domestic")


@pytest.mark.asyncio
async def test_update_multiple_immutable_fields_raises(service):
    """여러 불변 필드 동시 수정 시도 시 AccountImmutableFieldError 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError):
        await service.update("test", exchange="NYSE", currency="USD")


# ── 허용 필드 수정은 정상 동작 ──────────────────────


@pytest.mark.asyncio
async def test_update_mutable_name_succeeds(service):
    """name 수정은 정상 동작."""
    await service.create(_make_account())
    updated = await service.update("test", name="새이름")
    assert updated.name == "새이름"


@pytest.mark.asyncio
async def test_update_mutable_timezone_succeeds(service):
    """timezone 수정은 정상 동작."""
    await service.create(_make_account())
    updated = await service.update("test", timezone="US/Eastern")
    assert updated.timezone == "US/Eastern"


@pytest.mark.asyncio
async def test_update_mutable_with_immutable_raises(service):
    """허용 필드와 불변 필드를 함께 보내면 불변 필드 에러가 발생."""
    await service.create(_make_account())
    with pytest.raises(AccountImmutableFieldError, match="exchange"):
        await service.update("test", name="새이름", exchange="NYSE")


# ── 미인식 필드 거부 ─────────────────────────────────


@pytest.mark.asyncio
async def test_update_unrecognized_field_raises(service):
    """updatable에도 IMMUTABLE_FIELDS에도 없는 필드는 ValueError 발생."""
    await service.create(_make_account())
    with pytest.raises(ValueError, match="foo"):
        await service.update("test", foo="bar")


@pytest.mark.asyncio
async def test_update_multiple_unrecognized_fields_raises(service):
    """여러 미인식 필드 전달 시 모든 필드명이 에러 메시지에 포함."""
    await service.create(_make_account())
    with pytest.raises(ValueError, match="abc.*xyz|xyz.*abc"):
        await service.update("test", abc="1", xyz="2")


@pytest.mark.asyncio
async def test_update_unrecognized_with_valid_raises(service):
    """유효한 필드와 미인식 필드를 함께 보내면 ValueError 발생."""
    await service.create(_make_account())
    with pytest.raises(ValueError, match="unknown"):
        await service.update("test", name="새이름", unknown="value")
