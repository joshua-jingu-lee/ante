"""Account 모듈 단위 테스트."""

from decimal import Decimal

import pytest
import pytest_asyncio

from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountDeletedException,
    AccountNotFoundError,
    BrokerReconnectFailedError,
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
    이후 update()가 적용되어야 한다. 새로 생성된 어댑터는 connect()까지
    수행되어야 이후 호출에서 즉시 사용 가능하다.
    """
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    await broker_before.connect()
    assert broker_before.config.get("app_key") == "test"
    assert broker_before.is_connected is True

    await service.update("test", credentials={"app_key": "new", "app_secret": "new"})
    broker_after = await service.get_broker("test")

    assert broker_after is not broker_before
    assert broker_after.config.get("app_key") == "new"
    # 새 어댑터는 재연결되어 즉시 사용 가능해야 한다.
    assert broker_after.is_connected is True
    # 이전 어댑터는 장기 실행 consumer가 참조하고 있을 수 있으므로
    # 의도적으로 disconnect하지 않는다 (spec: 04-account-service.md 참고).
    assert broker_before.is_connected is True


@pytest.mark.asyncio
async def test_update_broker_config_invalidates_broker_cache(service):
    """broker_config 수정 시 캐시된 브로커를 무효화하고 재연결한다."""
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    await broker_before.connect()
    assert "is_paper" not in broker_before.config

    await service.update("test", broker_config={"is_paper": True})
    broker_after = await service.get_broker("test")

    assert broker_after is not broker_before
    assert broker_after.config.get("is_paper") is True
    assert broker_after.is_connected is True
    # 이전 어댑터는 의도적으로 disconnect하지 않는다 — 장기 실행 consumer
    # 회귀 방지.
    assert broker_before.is_connected is True


@pytest.mark.asyncio
async def test_update_commission_rate_invalidates_broker_cache(service):
    """수수료율 수정 시 캐시된 브로커를 무효화해 새 수수료가 즉시 반영된다.

    회귀 방지: 브로커 어댑터는 생성 시점에 수수료율을 고정하므로,
    update() 후에도 캐시를 유지하면 이후 체결/수수료 계산이 계속 이전
    값으로 수행된다.
    """
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    await broker_before.connect()
    assert float(broker_before.config.get("buy_commission_rate", 0.0)) == 0.0

    await service.update(
        "test",
        buy_commission_rate=Decimal("0.0015"),
        sell_commission_rate=Decimal("0.0025"),
    )
    broker_after = await service.get_broker("test")

    assert broker_after is not broker_before
    assert float(broker_after.config.get("buy_commission_rate")) == pytest.approx(
        0.0015
    )
    assert float(broker_after.config.get("sell_commission_rate")) == pytest.approx(
        0.0025
    )
    assert broker_after.is_connected is True


@pytest.mark.asyncio
async def test_update_non_broker_fields_preserves_broker_cache(service):
    """브로커와 무관한 필드(name 등) 수정 시 캐시는 유지된다."""
    await service.create(_make_account())
    broker_before = await service.get_broker("test")

    await service.update("test", name="renamed")
    broker_after = await service.get_broker("test")

    assert broker_after is broker_before


@pytest.mark.asyncio
async def test_update_does_not_disconnect_broker_held_by_long_running_consumer(service):
    """재연결 시 장기 실행 consumer가 붙잡은 기존 어댑터를 끊지 않는다.

    회귀 방지: ReconcileScheduler / Treasury.start_sync() 같은 장기 실행
    consumer는 시작 시점에 주입받은 BrokerAdapter 객체를 내부에 고정해
    계속 사용한다. credentials/broker_config 업데이트가 성공한 직후 기존
    어댑터를 disconnect하면 consumer가 붙잡은 세션이 바로 닫혀 주기 대사와
    잔고 동기화가 깨진다. 본 테스트는 consumer가 보유한 레퍼런스가 update
    이후에도 여전히 연결 상태를 유지하고, 실제 broker operation을 계속
    수행할 수 있음을 검증한다.
    """
    await service.create(_make_account())
    held_by_consumer = await service.get_broker("test")
    await held_by_consumer.connect()
    assert held_by_consumer.is_connected is True

    # consumer는 참조를 붙잡고 있으면서 주기적으로 broker operation을 호출한다.
    baseline_balance = await held_by_consumer.get_account_balance()
    assert isinstance(baseline_balance, dict)

    # credentials 업데이트 — 캐시는 새 어댑터로 교체되지만 consumer의 참조는
    # 끊기면 안 된다.
    await service.update(
        "test", credentials={"app_key": "rotated", "app_secret": "rotated"}
    )

    # consumer가 붙잡은 어댑터는 여전히 연결된 상태로 동작해야 한다.
    assert held_by_consumer.is_connected is True
    post_update_balance = await held_by_consumer.get_account_balance()
    assert isinstance(post_update_balance, dict)

    # 새로 get_broker를 호출한 경로(APIGateway 등)는 교체된 어댑터를 받는다.
    cached_now = await service.get_broker("test")
    assert cached_now is not held_by_consumer
    assert cached_now.is_connected is True
    assert cached_now.config.get("app_key") == "rotated"


@pytest.mark.asyncio
async def test_update_without_cached_broker_is_noop(service):
    """캐시에 어댑터가 없으면 broker_invalidating 필드 수정도 오류 없이 통과한다.

    회귀 방지: 부팅 중 레거시 is_paper 마이그레이션처럼, 아직 get_broker()가
    한 번도 불리지 않은 시점에 update(broker_config=...)가 호출되는 경우가
    있다. 재연결은 이미 생성돼 있는 어댑터를 교체하는 작업이므로 캐시
    부재 시점에는 의미가 없어야 하며, update는 DB 반영만 하고 조용히
    통과해야 한다. 이후 get_broker()가 새 설정으로 lazy init한다.
    """
    await service.create(_make_account())
    assert "test" not in service._brokers  # 아직 get_broker 호출 전

    # broker_config 변경 — 캐시가 비어 있어 재연결은 noop이어야 한다
    await service.update("test", broker_config={"is_paper": True})

    account = await service.get("test")
    assert account.broker_config == {"is_paper": True}
    # 캐시는 여전히 비어 있어야 한다 (lazy init은 이후 get_broker가 담당)
    assert "test" not in service._brokers

    # lazy init 후 새 설정이 반영되어야 한다
    broker = await service.get_broker("test")
    assert broker.config.get("is_paper") is True


@pytest.mark.asyncio
async def test_update_preserves_cache_when_new_broker_connect_fails(
    service, monkeypatch
):
    """새 브로커 connect 실패 시 기존 캐시를 보존하고 예외를 전파한다.

    회귀 방지: 일시적 인증/네트워크 오류로 새 어댑터 connect가 실패해도,
    캐시에 `is_connected=False`인 stale 어댑터가 남아 후속 gateway 호출이
    연쇄적으로 깨지는 상황을 차단한다. 기존 캐시(이전 설정으로 연결된
    브로커)는 그대로 유지되며, update 호출자는 BrokerReconnectFailedError를
    받는다. DB에는 새 설정이 이미 반영된 상태다.
    """
    await service.create(_make_account())
    broker_before = await service.get_broker("test")
    await broker_before.connect()
    assert broker_before.is_connected is True

    # 새 어댑터의 connect만 실패하도록 강제
    from ante.broker.test import TestBrokerAdapter

    async def fail_connect(self):  # noqa: ANN001
        raise RuntimeError("connect 실패 — 시뮬레이션")

    monkeypatch.setattr(TestBrokerAdapter, "connect", fail_connect)

    with pytest.raises(BrokerReconnectFailedError):
        await service.update(
            "test", credentials={"app_key": "new", "app_secret": "new"}
        )

    # 캐시는 기존 브로커를 그대로 유지해야 한다
    cached = await service.get_broker("test")
    assert cached is broker_before
    assert cached.is_connected is True

    # DB에는 새 설정이 반영되어 있음 (재시도 시 새 credentials로 생성됨)
    account = await service.get("test")
    assert account.credentials == {"app_key": "new", "app_secret": "new"}


@pytest.mark.asyncio
async def test_broker_operations_work_after_credentials_update(service):
    """health check가 브로커를 캐시한 뒤 credentials 업데이트가 즉시 반영된다.

    회귀 시나리오: 헬스체크가 주기적으로 get_broker를 호출해 어댑터를 미리
    캐시한 상태에서 사용자가 credentials를 변경해도, 이후 gateway 호출
    경로(get_broker → broker 메서드)가 새 설정의 연결된 어댑터로 동작해야 한다.
    AccountService.update가 단순히 캐시를 pop만 하고 재연결하지 않으면
    APIGateway는 is_connected=False 상태의 새 어댑터를 받아 실제 호출이
    깨진다 — 본 테스트는 그 회귀를 방지한다.
    """
    await service.create(_make_account())

    # 1) health check 경로: 미리 get_broker를 호출해 캐시 생성
    pre_broker = await service.get_broker("test")
    await pre_broker.connect()
    assert pre_broker.is_connected is True

    # 2) 운영 중 credentials 변경
    await service.update(
        "test",
        credentials={"app_key": "rotated", "app_secret": "rotated"},
    )

    # 3) gateway 호출 경로: get_broker가 반환한 어댑터로 즉시 operation 실행
    post_broker = await service.get_broker("test")
    assert post_broker is not pre_broker
    assert post_broker.is_connected is True
    # 실제 브로커 오퍼레이션이 바로 동작해야 한다 (별도 connect 없이 호출 가능)
    balance = await post_broker.get_account_balance()
    assert isinstance(balance, dict)


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
