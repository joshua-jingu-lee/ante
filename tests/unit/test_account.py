"""Account 모듈 단위 테스트."""

from decimal import Decimal

import pytest
import pytest_asyncio

from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountDeletedException,
    AccountNotFoundError,
    InvalidAccountIdError,
    InvalidBrokerTypeError,
    MissingCredentialsError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.presets import BROKER_PRESETS
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 인메모리 DB."""
    db_path = str(tmp_path / "test_account.db")
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


# ── 생성 (create) ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_account(service):
    """계좌 생성 후 조회 가능."""
    account = _make_account()
    result = await service.create(account)

    assert result.account_id == "test"
    assert result.name == "테스트"
    assert result.exchange == "TEST"
    assert result.currency == "KRW"
    assert result.broker_type == "test"
    assert result.status == AccountStatus.ACTIVE
    assert result.created_at is not None
    assert result.updated_at is not None


@pytest.mark.asyncio
async def test_create_duplicate_raises(service):
    """중복 account_id 생성 시 에러."""
    await service.create(_make_account())

    with pytest.raises(AccountAlreadyExistsError):
        await service.create(_make_account())


@pytest.mark.asyncio
async def test_create_soft_deleted_duplicate_raises(service):
    """soft-delete된 계좌와 동일 ID로 생성 시 AccountAlreadyExistsError."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="system")

    # 메모리에서는 제거되었지만 DB에 deleted 상태로 남아 있음
    with pytest.raises(AccountAlreadyExistsError, match="삭제 상태"):
        await service.create(_make_account())


@pytest.mark.asyncio
async def test_create_invalid_broker_type_raises(service):
    """잘못된 broker_type 생성 시 에러."""
    account = _make_account(broker_type="nonexistent-broker")

    with pytest.raises(InvalidBrokerTypeError):
        await service.create(account)


# ── credentials 필수 키 검증 ──────────────────────────


@pytest.mark.asyncio
async def test_create_missing_credentials_raises(service):
    """필수 credentials 키 누락 시 MissingCredentialsError."""
    account = _make_account(credentials={})

    with pytest.raises(MissingCredentialsError, match="app_key"):
        await service.create(account)


@pytest.mark.asyncio
async def test_create_partial_credentials_raises(service):
    """일부 credentials 키만 제공 시 누락 키를 메시지에 포함."""
    account = _make_account(credentials={"app_key": "key1"})

    with pytest.raises(MissingCredentialsError, match="app_secret"):
        await service.create(account)


@pytest.mark.asyncio
async def test_create_full_credentials_passes(service):
    """모든 필수 credentials 제공 시 정상 생성."""
    account = _make_account(
        credentials={"app_key": "key1", "app_secret": "secret1"},
    )
    result = await service.create(account)

    assert result.account_id == "test"
    assert result.credentials["app_key"] == "key1"


# ── account_id 형식 검증 ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "ab",
        "a" * 31,
        "has space",
        "has_under",
        "id@#$",
    ],
)
async def test_create_invalid_account_id_raises(service, bad_id):
    """형식 미준수 account_id로 생성 시 InvalidAccountIdError."""
    account = _make_account(account_id=bad_id)

    with pytest.raises(InvalidAccountIdError):
        await service.create(account)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "good_id",
    [
        "abc",
        "a" * 30,
        "test",
        "my-account-01",
        "ABC",
        "Test-123",
    ],
)
async def test_create_valid_account_id_passes(service, good_id):
    """형식 준수 account_id로 생성 시 정상 통과."""
    account = _make_account(account_id=good_id)
    result = await service.create(account)

    assert result.account_id == good_id


# ── 조회 (get / list) ──────────────────────────────


@pytest.mark.asyncio
async def test_get_account(service):
    """계좌 조회 성공."""
    await service.create(_make_account())

    result = await service.get("test")
    assert result.account_id == "test"


@pytest.mark.asyncio
async def test_get_not_found_raises(service):
    """존재하지 않는 계좌 조회 시 에러."""
    with pytest.raises(AccountNotFoundError):
        await service.get("nonexistent")


@pytest.mark.asyncio
async def test_list_accounts(service):
    """계좌 목록 조회."""
    await service.create(_make_account("acc1", broker_type="test"))
    await service.create(_make_account("acc2", broker_type="test"))

    accounts = await service.list()
    assert len(accounts) == 2


@pytest.mark.asyncio
async def test_list_by_status(service):
    """상태별 계좌 목록 필터."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.suspend("acc2", reason="테스트", suspended_by="system")

    active = await service.list(status=AccountStatus.ACTIVE)
    suspended = await service.list(status=AccountStatus.SUSPENDED)

    assert len(active) == 1
    assert len(suspended) == 1
    assert active[0].account_id == "acc1"
    assert suspended[0].account_id == "acc2"


# ── 수정 (update) ──────────────────────────────────


@pytest.mark.asyncio
async def test_update_account(service):
    """계좌 부분 수정."""
    await service.create(_make_account())

    result = await service.update("test", name="수정된 이름")
    assert result.name == "수정된 이름"

    # DB에서 다시 로드해도 동일
    fetched = await service.get("test")
    assert fetched.name == "수정된 이름"


@pytest.mark.asyncio
async def test_update_deleted_raises(service):
    """삭제된 계좌 수정 시 에러."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.update("test", name="변경 시도")


# ── 정지/활성화 (suspend / activate) ──────────────────


@pytest.mark.asyncio
async def test_suspend_account(service):
    """계좌 정지."""
    await service.create(_make_account())
    await service.suspend("test", reason="위험 감지", suspended_by="rule-engine")

    account = await service.get("test")
    assert account.status == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_activate_account(service):
    """정지된 계좌 활성화."""
    await service.create(_make_account())
    await service.suspend("test", reason="테스트", suspended_by="system")
    await service.activate("test", activated_by="admin")

    account = await service.get("test")
    assert account.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_activate_deleted_raises(service):
    """삭제된 계좌 활성화 시 에러."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.activate("test", activated_by="admin")


@pytest.mark.asyncio
async def test_suspend_deleted_account_raises(service):
    """DELETED 계좌에 suspend 시도 시 AccountDeletedException."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.suspend("test", reason="테스트", suspended_by="system")


@pytest.mark.asyncio
async def test_delete_already_deleted_account_raises(service):
    """이미 DELETED 계좌에 delete 시도 시 AccountDeletedException."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.delete("test", deleted_by="system")


# ── 삭제 (delete) ──────────────────────────────────


@pytest.mark.asyncio
async def test_delete_account(service):
    """계좌 소프트 딜리트."""
    await service.create(_make_account())
    await service.delete("test", deleted_by="admin")

    # 기본 목록에서는 안 보임
    accounts = await service.list()
    assert len(accounts) == 0

    # DELETED 상태도 조회 가능
    deleted = await service.get("test")
    assert deleted.status == AccountStatus.DELETED


# ── 일괄 정지/활성화 (suspend_all / activate_all) ──────


@pytest.mark.asyncio
async def test_suspend_all(service):
    """모든 ACTIVE 계좌 정지. DELETED 제외."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.create(_make_account("acc3"))
    await service.delete("acc3", deleted_by="system")

    count = await service.suspend_all(reason="시스템 긴급 정지", suspended_by="system")

    assert count == 2  # acc3 (DELETED) 제외
    accounts = await service.list(status=AccountStatus.ACTIVE)
    assert len(accounts) == 0


@pytest.mark.asyncio
async def test_activate_all(service):
    """모든 SUSPENDED 계좌 활성화. DELETED 제외."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.suspend("acc1", reason="테스트", suspended_by="system")
    await service.suspend("acc2", reason="테스트", suspended_by="system")

    count = await service.activate_all(activated_by="admin")

    assert count == 2
    accounts = await service.list(status=AccountStatus.ACTIVE)
    assert len(accounts) == 2


# ── 브로커 인스턴스 (get_broker) ──────────────────────


@pytest.mark.asyncio
async def test_get_broker_test(service):
    """test broker_type으로 TestBrokerAdapter 반환."""
    await service.create(_make_account())

    broker = await service.get_broker("test")
    assert broker.broker_id == "test"


@pytest.mark.asyncio
async def test_get_broker_cached(service):
    """두 번 호출 시 같은 인스턴스 반환 (캐싱)."""
    await service.create(_make_account())

    broker1 = await service.get_broker("test")
    broker2 = await service.get_broker("test")
    assert broker1 is broker2


@pytest.mark.asyncio
async def test_get_broker_uses_broker_config(service):
    """broker_config={"is_paper": True} -> config에 전달."""
    await service.create(
        _make_account(broker_config={"is_paper": True}),
    )
    broker = await service.get_broker("test")
    assert broker.config.get("is_paper") is True


@pytest.mark.asyncio
async def test_get_broker_broker_config_default(service):
    """broker_config={} -> is_paper 키 없음 (KIS 기본값 사용)."""
    await service.create(_make_account())
    broker = await service.get_broker("test")
    assert "is_paper" not in broker.config


@pytest.mark.asyncio
async def test_update_credentials_invalidates_broker_cache(service):
    """credentials 수정 시 캐시된 브로커를 무효화하여 새 값을 즉시 반영한다.

    회귀 방지: health check가 미리 get_broker를 호출해 캐시를 만든 뒤에도
    이후 update()가 적용되어야 한다.
    """
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    assert broker_before.config.get("app_key") == "test"

    await service.update("test", credentials={"app_key": "new", "app_secret": "new"})
    broker_after = await service.get_broker("test")

    assert broker_after is not broker_before
    assert broker_after.config.get("app_key") == "new"


@pytest.mark.asyncio
async def test_update_broker_config_invalidates_broker_cache(service):
    """broker_config 수정 시 캐시된 브로커를 무효화한다."""
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    assert "is_paper" not in broker_before.config

    await service.update("test", broker_config={"is_paper": True})
    broker_after = await service.get_broker("test")

    assert broker_after is not broker_before
    assert broker_after.config.get("is_paper") is True


@pytest.mark.asyncio
async def test_update_non_broker_fields_preserves_broker_cache(service):
    """브로커와 무관한 필드(name 등) 수정 시 캐시는 유지된다."""
    await service.create(_make_account())
    broker_before = await service.get_broker("test")

    await service.update("test", name="renamed")
    broker_after = await service.get_broker("test")

    assert broker_after is broker_before


@pytest.mark.asyncio
async def test_create_account_with_broker_config(service):
    """생성 시 broker_config가 DB에 저장/로드."""
    account = _make_account(broker_config={"is_paper": True, "hts_id": "myid"})
    created = await service.create(account)

    assert created.broker_config == {"is_paper": True, "hts_id": "myid"}

    # DB에서 다시 로드
    fetched = await service.get("test")
    assert fetched.broker_config == {"is_paper": True, "hts_id": "myid"}


# ── 기본 테스트 계좌 ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_default_test_account(service):
    """기본 테스트 계좌 자동 생성."""
    account = await service.create_default_test_account()

    assert account.account_id == "test"
    assert account.exchange == "TEST"
    assert account.trading_mode == TradingMode.VIRTUAL
    assert account.broker_type == "test"


@pytest.mark.asyncio
async def test_create_default_test_account_idempotent(service):
    """이미 존재하면 기존 계좌 반환 (멱등성)."""
    first = await service.create_default_test_account()
    second = await service.create_default_test_account()

    assert first.account_id == second.account_id


# ── DB 영속성 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_db_persistence(db, eventbus):
    """서비스 재시작 후에도 DB에서 계좌 복원."""
    svc1 = AccountService(db, eventbus)
    await svc1.initialize()
    await svc1.create(_make_account())

    # 새 서비스 인스턴스로 재초기화
    svc2 = AccountService(db, eventbus)
    await svc2.initialize()

    accounts = await svc2.list()
    assert len(accounts) == 1
    assert accounts[0].account_id == "test"


# ── 프리셋 ──────────────────────────────────────────


def test_broker_presets_defined():
    """test, kis-domestic 프리셋이 정의되어 있음."""
    assert "test" in BROKER_PRESETS
    assert "kis-domestic" in BROKER_PRESETS


def test_broker_preset_test_values():
    """test 프리셋 기본값 확인."""
    preset = BROKER_PRESETS["test"]
    assert preset.exchange == "TEST"
    assert preset.currency == "KRW"
    assert preset.buy_commission_rate == Decimal("0")
    assert preset.sell_commission_rate == Decimal("0")
    assert preset.required_credentials == ["app_key", "app_secret"]


def test_broker_preset_kis_domestic_values():
    """kis-domestic 프리셋 기본값 확인."""
    preset = BROKER_PRESETS["kis-domestic"]
    assert preset.exchange == "KRX"
    assert preset.currency == "KRW"
    assert preset.buy_commission_rate == Decimal("0.00015")
    assert preset.sell_commission_rate == Decimal("0.00195")
    assert "app_key" in preset.required_credentials
