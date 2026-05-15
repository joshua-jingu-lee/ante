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
    InvalidExchangeError,
    MissingCredentialsError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.presets import BROKER_PRESETS
from ante.account.service import AccountService
from ante.core.database import Database
from ante.core.exchange import CANONICAL_EXCHANGES
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
    account_id: str = "main",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    **kwargs,
) -> Account:
    """테스트용 Account 생성 헬퍼.

    default ``account_id``는 ``"main"``이다. ``"test"``는 bootstrap seed
    예약어라 :func:`validate_new_account_id`가 신규 생성을 거부하므로
    직접 helper에서는 ``ante.account.scoping.RESTRICTED_NEW_ACCOUNT_IDS``
    바깥의 valid ID를 사용한다 (``docs/specs/account/14-account-id-contract.md``).
    """
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

    assert result.account_id == "main"
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
    await service.delete("main", deleted_by="system")

    # 메모리에서는 제거되었지만 DB에 deleted 상태로 남아 있음
    with pytest.raises(AccountAlreadyExistsError, match="삭제 상태"):
        await service.create(_make_account())


@pytest.mark.asyncio
async def test_create_invalid_broker_type_raises(service):
    """잘못된 broker_type 생성 시 에러."""
    account = _make_account(broker_type="nonexistent-broker")

    with pytest.raises(InvalidBrokerTypeError):
        await service.create(account)


# ── exchange canonical 검증 (ante.core.exchange SSOT, core.md 축 A) ──


@pytest.mark.asyncio
async def test_create_invalid_exchange_raises(service):
    """canonical vocabulary 밖 exchange는 InvalidExchangeError로 거부.

    broker_type 검증과 같은 _persist_account chokepoint에서 차단된다
    (#1583). 메시지에 허용 canonical 값 목록을 노출한다.
    """
    account = _make_account(exchange="LSE")

    with pytest.raises(InvalidExchangeError, match="유효하지 않은 exchange"):
        await service.create(account)


@pytest.mark.asyncio
async def test_create_wildcard_exchange_raises(service):
    """`*`(StrategyMeta 전용 wildcard)는 account 표면에서 거부 (core.md 축 A)."""
    account = _make_account(exchange="*")

    with pytest.raises(InvalidExchangeError):
        await service.create(account)


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange", sorted(CANONICAL_EXCHANGES))
async def test_create_canonical_exchange_passes_service_gate(service, exchange):
    """canonical 5종은 _persist_account exchange 게이트를 통과 (축 A).

    service layer 직접 생성으로 exchange 게이트만 검증한다 — preset/
    credential 결합(축 B)이 테스트 의미를 왜곡하지 않도록 모든 케이스가
    test preset을 충족하는 broker_type="test" + test credentials를 쓴다
    (NYSE/NASDAQ/AMEX는 exchange 게이트 통과만 확인). canonical 5종은
    어떤 경우에도 invalid exchange로 거부되지 않는다.
    """
    account = _make_account(account_id=f"acct-{exchange.lower()}", exchange=exchange)

    result = await service.create(account)

    assert result.exchange == exchange
    assert result.status == AccountStatus.ACTIVE


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

    assert result.account_id == "main"
    assert result.credentials["app_key"] == "key1"


# ── account_id 형식 검증 (helper SSOT) ────────────────


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
    """형식 미준수 account_id로 생성 시 InvalidAccountIdError.

    형식 위반 메시지 형식은 ``ante account create`` CLI 표면 contract이므로
    ``validate_new_account_id`` helper에서도 동일하게 보존된다
    (docs/specs/account/14-account-id-contract.md).
    """
    account = _make_account(account_id=bad_id)

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service.create(account)

    msg = str(exc_info.value)
    assert "account_id 형식이 올바르지 않습니다" in msg
    assert "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다." in msg


@pytest.mark.asyncio
async def test_create_default_account_id_raises(service):
    """``"default"``는 fallback 예약어로 신규 생성 거부 (#1216)."""
    account = _make_account(account_id="default")

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service.create(account)

    assert "fallback" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_test_account_id_raises_for_user(service):
    """``"test"``는 bootstrap seed 예약어로 사용자 신규 생성 거부 (#1216).

    ``ante init`` 경로( :meth:`AccountService.create_default_test_account` )는
    private :meth:`AccountService._create_seed_account` helper를 통해서만
    seed 계좌를 만들 수 있다 (#1216 P2). public ``create()`` API에는 우회
    플래그가 노출되지 않으므로, 외부 호출자가 ``"test"`` 를 신규 생성하는
    경로는 이 가드에서 차단된다.
    """
    account = _make_account(account_id="test")

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service.create(account)

    assert "ante init" in str(exc_info.value)
    assert "시드 계좌" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "good_id",
    [
        "abc",
        "a" * 30,
        "main",
        "my-account-01",
        "ABC",
        "Test-123",
    ],
)
async def test_create_valid_account_id_passes(service, good_id):
    """형식 준수 + non-RESTRICTED account_id로 생성 시 정상 통과."""
    account = _make_account(account_id=good_id)
    result = await service.create(account)

    assert result.account_id == good_id


# ── 조회 (get / list) ──────────────────────────────


@pytest.mark.asyncio
async def test_get_account(service):
    """계좌 조회 성공."""
    await service.create(_make_account())

    result = await service.get("main")
    assert result.account_id == "main"


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

    result = await service.update("main", name="수정된 이름")
    assert result.name == "수정된 이름"

    # DB에서 다시 로드해도 동일
    fetched = await service.get("main")
    assert fetched.name == "수정된 이름"


@pytest.mark.asyncio
async def test_update_deleted_raises(service):
    """삭제된 계좌 수정 시 에러."""
    await service.create(_make_account())
    await service.delete("main", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.update("main", name="변경 시도")


# ── 정지/활성화 (suspend / activate) ──────────────────


@pytest.mark.asyncio
async def test_suspend_account(service):
    """계좌 정지."""
    await service.create(_make_account())
    await service.suspend("main", reason="위험 감지", suspended_by="rule-engine")

    account = await service.get("main")
    assert account.status == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_activate_account(service):
    """정지된 계좌 활성화."""
    await service.create(_make_account())
    await service.suspend("main", reason="테스트", suspended_by="system")
    await service.activate("main", activated_by="admin")

    account = await service.get("main")
    assert account.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_activate_deleted_raises(service):
    """삭제된 계좌 활성화 시 에러."""
    await service.create(_make_account())
    await service.delete("main", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.activate("main", activated_by="admin")


@pytest.mark.asyncio
async def test_suspend_deleted_account_raises(service):
    """DELETED 계좌에 suspend 시도 시 AccountDeletedException."""
    await service.create(_make_account())
    await service.delete("main", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.suspend("main", reason="테스트", suspended_by="system")


@pytest.mark.asyncio
async def test_delete_already_deleted_account_raises(service):
    """이미 DELETED 계좌에 delete 시도 시 AccountDeletedException."""
    await service.create(_make_account())
    await service.delete("main", deleted_by="system")

    with pytest.raises(AccountDeletedException):
        await service.delete("main", deleted_by="system")


# ── 삭제 (delete) ──────────────────────────────────


@pytest.mark.asyncio
async def test_delete_account(service):
    """계좌 소프트 딜리트."""
    await service.create(_make_account())
    await service.delete("main", deleted_by="admin")

    # 기본 목록에서는 안 보임
    accounts = await service.list()
    assert len(accounts) == 0

    # DELETED 상태도 조회 가능
    deleted = await service.get("main")
    assert deleted.status == AccountStatus.DELETED


# ── delete preflight: active bot 차단 ──────────────────


@pytest.mark.asyncio
async def test_delete_raises_when_active_bots_present(service, db):
    """non-deleted 봇이 있으면 delete가 AccountHasActiveBotsError로 차단된다.

    bots 테이블에 status != 'deleted' 행이 있으면 status mutation 전에
    AccountHasActiveBotsError가 raise되어야 하며, 계좌 status는 ACTIVE 그대로
    유지되어야 한다.
    """
    from ante.account.errors import AccountHasActiveBotsError
    from ante.bot.manager import BOT_SCHEMA

    await service.create(_make_account())
    await db.execute_script(BOT_SCHEMA)
    await db.execute(
        """INSERT INTO bots
           (bot_id, name, strategy_id, account_id, config_json, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("bot-1", "테스트봇", "strat", "main", "{}", "running"),
    )

    with pytest.raises(AccountHasActiveBotsError) as excinfo:
        await service.delete("main", deleted_by="admin")

    assert excinfo.value.account_id == "main"
    assert excinfo.value.bot_count == 1

    # 계좌 status는 ACTIVE 그대로 유지되어야 함
    account = await service.get("main")
    assert account.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_delete_succeeds_when_no_active_bots(service, db):
    """bots 테이블이 비어 있으면 delete는 정상 진행된다."""
    from ante.bot.manager import BOT_SCHEMA

    await service.create(_make_account())
    # 빈 bots 테이블
    await db.execute_script(BOT_SCHEMA)

    await service.delete("main", deleted_by="admin")

    deleted = await service.get("main")
    assert deleted.status == AccountStatus.DELETED


@pytest.mark.asyncio
async def test_delete_succeeds_when_only_deleted_bots(service, db):
    """같은 account_id에 status='deleted' 봇만 있으면 delete 정상 진행."""
    from ante.bot.manager import BOT_SCHEMA

    await service.create(_make_account())
    await db.execute_script(BOT_SCHEMA)
    await db.execute(
        """INSERT INTO bots
           (bot_id, name, strategy_id, account_id, config_json, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("bot-old", "삭제봇", "strat", "main", "{}", "deleted"),
    )

    await service.delete("main", deleted_by="admin")

    deleted = await service.get("main")
    assert deleted.status == AccountStatus.DELETED


@pytest.mark.asyncio
async def test_delete_error_message_includes_cold_path_bot_remove_procedure(
    service, db
):
    """AccountHasActiveBotsError 메시지는 cold-path bot remove 복구 절차를 안내한다."""
    import re

    from ante.account.errors import AccountHasActiveBotsError
    from ante.bot.manager import BOT_SCHEMA

    await service.create(_make_account())
    await db.execute_script(BOT_SCHEMA)
    await db.execute(
        """INSERT INTO bots
           (bot_id, name, strategy_id, account_id, config_json, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("bot-1", "테스트봇", "strat", "main", "{}", "running"),
    )

    with pytest.raises(AccountHasActiveBotsError) as excinfo:
        await service.delete("main", deleted_by="admin")

    message = str(excinfo.value)

    # account_id / bot_count 포함
    assert "main" in message
    assert "1" in message

    # server start/stop 없이 bot remove → account delete 순서만 안내한다 (#1161).
    assert "ante system start" not in message
    assert "ante system stop" not in message
    assert "ante bot remove" in message
    assert "ante account delete" in message
    assert "서버 정지 상태에서도 가능" in message

    # 정확한 순서로 등장해야 한다 (multi-step 절차의 핵심)
    order_pattern = re.compile(
        r"ante bot remove.*?ante account delete",
        re.DOTALL,
    )
    assert order_pattern.search(message) is not None, (
        f"cold-path 복구 절차가 정확한 순서로 메시지에 포함되어야 한다: {message!r}"
    )


# ── 일괄 정지/활성화 (suspend_all / activate_all) ──────


@pytest.mark.asyncio
async def test_suspend_all(service):
    """모든 ACTIVE 계좌 정지. DELETED 제외.

    SSOT (`docs/specs/web-api/04-system-endpoints.md`): 반환은 처리 대상 계좌
    list (DELETED 제외). 각 항목은 ``account_id``, ``previous_status``, ``status``,
    ``changed`` 4개 키만 포함한다.
    """
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.create(_make_account("acc3"))
    await service.delete("acc3", deleted_by="system")

    results = await service.suspend_all(
        reason="시스템 긴급 정지", suspended_by="system"
    )

    # acc3 (DELETED)은 후보에서 제외
    assert isinstance(results, list)
    assert len(results) == 2
    account_ids = {r["account_id"] for r in results}
    assert account_ids == {"acc1", "acc2"}
    for r in results:
        assert set(r.keys()) == {"account_id", "previous_status", "status", "changed"}
        assert r["previous_status"] == "active"
        assert r["status"] == "suspended"
        assert r["changed"] is True

    changed_count = sum(1 for r in results if r["changed"])
    assert changed_count == 2
    accounts = await service.list(status=AccountStatus.ACTIVE)
    assert len(accounts) == 0


@pytest.mark.asyncio
async def test_suspend_all_idempotent_for_already_suspended(service):
    """이미 SUSPENDED인 계좌는 응답에 포함되지만 changed=False."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.suspend("acc1", reason="이미 정지", suspended_by="system")

    results = await service.suspend_all(reason="긴급", suspended_by="system")

    assert {r["account_id"] for r in results} == {"acc1", "acc2"}
    by_id = {r["account_id"]: r for r in results}
    assert by_id["acc1"]["previous_status"] == "suspended"
    assert by_id["acc1"]["status"] == "suspended"
    assert by_id["acc1"]["changed"] is False
    assert by_id["acc2"]["previous_status"] == "active"
    assert by_id["acc2"]["status"] == "suspended"
    assert by_id["acc2"]["changed"] is True


@pytest.mark.asyncio
async def test_activate_all(service):
    """모든 SUSPENDED 계좌 활성화. DELETED 제외.

    SSOT (`docs/specs/web-api/04-system-endpoints.md`): 반환은 처리 대상 계좌
    list (DELETED 제외). 각 항목은 ``account_id``, ``previous_status``, ``status``,
    ``changed`` 4개 키만 포함한다.
    """
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.suspend("acc1", reason="테스트", suspended_by="system")
    await service.suspend("acc2", reason="테스트", suspended_by="system")

    results = await service.activate_all(activated_by="admin")

    assert isinstance(results, list)
    assert len(results) == 2
    for r in results:
        assert set(r.keys()) == {"account_id", "previous_status", "status", "changed"}
        assert r["previous_status"] == "suspended"
        assert r["status"] == "active"
        assert r["changed"] is True

    accounts = await service.list(status=AccountStatus.ACTIVE)
    assert len(accounts) == 2


@pytest.mark.asyncio
async def test_activate_all_idempotent_for_already_active(service):
    """이미 ACTIVE인 계좌는 응답에 포함되지만 changed=False."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.suspend("acc2", reason="테스트", suspended_by="system")

    results = await service.activate_all(activated_by="admin")

    by_id = {r["account_id"]: r for r in results}
    assert by_id["acc1"]["previous_status"] == "active"
    assert by_id["acc1"]["status"] == "active"
    assert by_id["acc1"]["changed"] is False
    assert by_id["acc2"]["previous_status"] == "suspended"
    assert by_id["acc2"]["status"] == "active"
    assert by_id["acc2"]["changed"] is True


@pytest.mark.asyncio
async def test_activate_all_excludes_deleted(service):
    """DELETED 계좌는 후보에서 제외 (응답 list에 미포함)."""
    await service.create(_make_account("acc1"))
    await service.create(_make_account("acc2"))
    await service.delete("acc2", deleted_by="system")

    results = await service.activate_all(activated_by="admin")

    assert {r["account_id"] for r in results} == {"acc1"}


# ── 브로커 인스턴스 (get_broker) ──────────────────────


@pytest.mark.asyncio
async def test_get_broker_test(service):
    """test broker_type으로 TestBrokerAdapter 반환."""
    await service.create(_make_account())

    broker = await service.get_broker("main")
    # TestBrokerAdapter.broker_id 클래스 default는 "test" — broker_type SSOT.
    assert broker.broker_id == "test"


@pytest.mark.asyncio
async def test_get_broker_cached(service):
    """두 번 호출 시 같은 인스턴스 반환 (캐싱)."""
    await service.create(_make_account())

    broker1 = await service.get_broker("main")
    broker2 = await service.get_broker("main")
    assert broker1 is broker2


@pytest.mark.asyncio
async def test_get_broker_uses_broker_config(service):
    """broker_config={"is_paper": True} -> config에 전달."""
    await service.create(
        _make_account(broker_config={"is_paper": True}),
    )
    broker = await service.get_broker("main")
    assert broker.config.get("is_paper") is True


@pytest.mark.asyncio
async def test_get_broker_broker_config_default(service):
    """broker_config={} -> is_paper 키 없음 (KIS 기본값 사용)."""
    await service.create(_make_account())
    broker = await service.get_broker("main")
    assert "is_paper" not in broker.config


@pytest.mark.asyncio
async def test_update_credentials_invalidates_broker_cache(service):
    """credentials 수정 시 캐시된 브로커를 무효화하여 새 값을 즉시 반영한다.

    회귀 방지: health check가 미리 get_broker를 호출해 캐시를 만든 뒤에도
    이후 update()가 적용되어야 한다. 새로 생성된 어댑터는 connect()까지
    수행되어야 이후 호출에서 즉시 사용 가능하다.
    """
    await service.create(_make_account())
    broker_before = await service.get_broker("main")
    await broker_before.connect()
    assert broker_before.config.get("app_key") == "test"
    assert broker_before.is_connected is True

    await service.update("main", credentials={"app_key": "new", "app_secret": "new"})
    broker_after = await service.get_broker("main")

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
    broker_before = await service.get_broker("main")
    await broker_before.connect()
    assert "is_paper" not in broker_before.config

    await service.update("main", broker_config={"is_paper": True})
    broker_after = await service.get_broker("main")

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
    broker_before = await service.get_broker("main")
    await broker_before.connect()
    assert float(broker_before.config.get("buy_commission_rate", 0.0)) == 0.0

    await service.update(
        "main",
        buy_commission_rate=Decimal("0.0015"),
        sell_commission_rate=Decimal("0.0025"),
    )
    broker_after = await service.get_broker("main")

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
    broker_before = await service.get_broker("main")

    await service.update("main", name="renamed")
    broker_after = await service.get_broker("main")

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
    held_by_consumer = await service.get_broker("main")
    await held_by_consumer.connect()
    assert held_by_consumer.is_connected is True

    # consumer는 참조를 붙잡고 있으면서 주기적으로 broker operation을 호출한다.
    baseline_balance = await held_by_consumer.get_account_balance()
    assert isinstance(baseline_balance, dict)

    # credentials 업데이트 — 캐시는 새 어댑터로 교체되지만 consumer의 참조는
    # 끊기면 안 된다.
    await service.update(
        "main", credentials={"app_key": "rotated", "app_secret": "rotated"}
    )

    # consumer가 붙잡은 어댑터는 여전히 연결된 상태로 동작해야 한다.
    assert held_by_consumer.is_connected is True
    post_update_balance = await held_by_consumer.get_account_balance()
    assert isinstance(post_update_balance, dict)

    # 새로 get_broker를 호출한 경로(APIGateway 등)는 교체된 어댑터를 받는다.
    cached_now = await service.get_broker("main")
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
    assert "main" not in service._brokers  # 아직 get_broker 호출 전

    # broker_config 변경 — 캐시가 비어 있어 재연결은 noop이어야 한다
    await service.update("main", broker_config={"is_paper": True})

    account = await service.get("main")
    assert account.broker_config == {"is_paper": True}
    # 캐시는 여전히 비어 있어야 한다 (lazy init은 이후 get_broker가 담당)
    assert "main" not in service._brokers

    # lazy init 후 새 설정이 반영되어야 한다
    broker = await service.get_broker("main")
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
    broker_before = await service.get_broker("main")
    await broker_before.connect()
    assert broker_before.is_connected is True

    # 새 어댑터의 connect만 실패하도록 강제
    from ante.broker.test import TestBrokerAdapter

    async def fail_connect(self):  # noqa: ANN001
        raise RuntimeError("connect 실패 — 시뮬레이션")

    monkeypatch.setattr(TestBrokerAdapter, "connect", fail_connect)

    with pytest.raises(BrokerReconnectFailedError):
        await service.update(
            "main", credentials={"app_key": "new", "app_secret": "new"}
        )

    # 캐시는 기존 브로커를 그대로 유지해야 한다
    cached = await service.get_broker("main")
    assert cached is broker_before
    assert cached.is_connected is True

    # DB에는 새 설정이 반영되어 있음 (재시도 시 새 credentials로 생성됨)
    account = await service.get("main")
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
    pre_broker = await service.get_broker("main")
    await pre_broker.connect()
    assert pre_broker.is_connected is True

    # 2) 운영 중 credentials 변경
    await service.update(
        "main",
        credentials={"app_key": "rotated", "app_secret": "rotated"},
    )

    # 3) gateway 호출 경로: get_broker가 반환한 어댑터로 즉시 operation 실행
    post_broker = await service.get_broker("main")
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
    fetched = await service.get("main")
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


# ── public create() seed 우회 차단 + private _create_seed_account 가드 (#1216 P2) ──


@pytest.mark.asyncio
async def test_create_public_api_has_no_bootstrap_kwarg(service):
    """public ``create()`` 시그니처는 ``_bootstrap`` 키워드를 받지 않는다 (#1216 P2).

    외부 호출자가 ``_bootstrap=True`` 로 RESTRICTED 예약어( ``"test"`` ) 검증을
    우회할 수 없도록 시그니처에서 완전히 제거됐는지 회귀 방지.
    """
    import inspect

    sig = inspect.signature(service.create)
    assert "_bootstrap" not in sig.parameters, (
        f"public create() must not expose _bootstrap kwarg; got params="
        f"{list(sig.parameters)}"
    )


@pytest.mark.asyncio
async def test_create_public_api_rejects_seed_id_for_test_broker(service):
    """seed account_id ``"test"`` 는 public ``create()`` 에서 broker_type 무관 거부.

    seed 우회가 사라졌으므로, 외부 호출자가 정확한 (broker_type, account_id)
    pair를 넘겨도 public 경로에서는 RESTRICTED 가드가 막아야 한다 (#1216 P2).
    bootstrap은 :meth:`AccountService.create_default_test_account` 만의 책임.
    """
    account = _make_account(account_id="test", broker_type="test")

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service.create(account)

    msg = str(exc_info.value)
    assert "ante init" in msg
    assert "시드 계좌" in msg


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    [
        "default",  # fallback 예약어
        "random",  # seed 화이트리스트 밖
        "main",  # 일반 valid이지만 seed 아님
        "ab",  # 형식 위반 (너무 짧음, 동시에 seed 아님)
    ],
)
async def test_create_seed_account_rejects_non_seed(service, bad_id):
    """private seed helper는 (broker_type, default_account_id) pair만 허용.

    오케스트레이션 helper(``create_default_test_account``)가 잘못된 입력을
    넘기더라도 'default'/패턴 위반/임의 ID가 슬쩍 통과되지 않게 막는
    defense-in-depth 가드 (#1216 P2). 여기서는
    broker_type='test'(default_account_id='test')와 mismatch인 케이스들이다.
    """
    account = _make_account(account_id=bad_id, broker_type="test")

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service._create_seed_account(account)

    msg = str(exc_info.value)
    assert "seed 계좌 생성" in msg
    assert "valid pairs" in msg


@pytest.mark.asyncio
async def test_create_seed_account_rejects_empty(service):
    """빈 문자열 account_id는 ``_create_seed_account`` 에서 거부된다 (pair 불일치)."""
    # _make_account의 default 분기로 직접 만들지 못하므로 명시적으로 구성.
    account = _make_account(account_id="", broker_type="test")

    with pytest.raises(InvalidAccountIdError):
        await service._create_seed_account(account)


@pytest.mark.asyncio
async def test_create_seed_account_accepts_seed_test(service):
    """정확한 (test, test) pair는 ``_create_seed_account`` 에서 통과한다."""
    preset = BROKER_PRESETS["test"]
    account = _make_account(
        account_id=preset.default_account_id,
        broker_type="test",
        credentials={k: "test" for k in preset.required_credentials},
    )

    result = await service._create_seed_account(account)

    assert result.account_id == "test"
    assert result.broker_type == "test"
    assert result.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_seed_account_accepts_seed_kis_domestic(service):
    """정확한 (kis-domestic, domestic) pair도 ``_create_seed_account`` 에서 통과.

    BROKER_PRESETS에 정의된 모든 pair가 동일하게 허용되는지 회귀 방지.
    """
    preset = BROKER_PRESETS["kis-domestic"]
    account = _make_account(
        account_id=preset.default_account_id,
        broker_type="kis-domestic",
        credentials={k: "test" for k in preset.required_credentials},
    )

    result = await service._create_seed_account(account)

    assert result.account_id == "domestic"
    assert result.broker_type == "kis-domestic"
    assert result.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_seed_account_rejects_seed_id_with_wrong_broker_type(service):
    """``account_id='test'`` + ``broker_type='kis-domestic'``는 거부된다 (#1216 P2).

    이전 구현은 account_id가 BROKER_PRESETS의 default_account_id set에
    포함되기만 하면 통과시켜, 호출자가 RESTRICTED 예약어 'test'를
    비-test broker 아래에 저장하는 우회가 가능했다. 새 가드는
    (broker_type, default_account_id) pair 정확 일치를 요구한다.
    """
    preset = BROKER_PRESETS["kis-domestic"]
    account = _make_account(
        account_id="test",  # test preset의 seed
        broker_type="kis-domestic",  # 그러나 broker_type은 다른 preset
        credentials={k: "test" for k in preset.required_credentials},
    )

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service._create_seed_account(account)

    msg = str(exc_info.value)
    assert "seed 계좌 생성" in msg
    assert "valid pairs" in msg
    assert "'test'" in msg  # 입력된 account_id가 메시지에 포함


@pytest.mark.asyncio
async def test_create_seed_account_rejects_cross_pair_domestic_with_test_broker(
    service,
):
    """``account_id='domestic'`` + ``broker_type='test'`` (반대 mismatch)도 거부."""
    account = _make_account(
        account_id="domestic",  # kis-domestic preset의 seed
        broker_type="test",  # 그러나 broker_type은 다른 preset
        credentials={"app_key": "test", "app_secret": "test"},
    )

    with pytest.raises(InvalidAccountIdError):
        await service._create_seed_account(account)


@pytest.mark.asyncio
async def test_create_seed_account_rejects_unknown_broker_type(service):
    """알 수 없는 ``broker_type`` 은 ``_create_seed_account`` pair 검증에서 거부된다.

    BROKER_PRESETS.get(broker_type)이 None이므로 InvalidBrokerTypeError가
    아니라 seed pair 가드가 먼저 InvalidAccountIdError로 차단한다.
    """
    account = _make_account(
        account_id="test",
        broker_type="bogus-broker",
        credentials={"app_key": "test", "app_secret": "test"},
    )

    with pytest.raises(InvalidAccountIdError) as exc_info:
        await service._create_seed_account(account)

    assert "seed 계좌 생성" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_default_test_account_seed_path_works(service):
    """``create_default_test_account`` 흐름이 새 helper 적용 후에도 정상 동작.

    회귀 방지: private ``_create_seed_account`` 경로의 pair 화이트리스트
    가드가 기존 bootstrap seed 자동 생성 흐름을 깨지 않아야 한다 (#1216 P2).
    """
    account = await service.create_default_test_account()

    assert account.account_id == "test"
    assert account.broker_type == "test"
    assert account.status == AccountStatus.ACTIVE
    # 멱등성도 함께 확인 (기존 계약 유지)
    again = await service.create_default_test_account()
    assert again.account_id == "test"


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
    assert accounts[0].account_id == "main"


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
    # #1333: market buy reserve buffer 기본값. test는 결정적 거동을 위해 0.
    assert preset.market_order_reserve_buffer_rate == Decimal("0")
    assert preset.required_credentials == ["app_key", "app_secret"]


def test_broker_preset_kis_domestic_values():
    """kis-domestic 프리셋 기본값 확인."""
    preset = BROKER_PRESETS["kis-domestic"]
    assert preset.exchange == "KRX"
    assert preset.currency == "KRW"
    assert preset.buy_commission_rate == Decimal("0.00015")
    assert preset.sell_commission_rate == Decimal("0.00195")
    # #1333: market buy reserve buffer 기본값 0.5%.
    assert preset.market_order_reserve_buffer_rate == Decimal("0.005")
    assert "app_key" in preset.required_credentials


# ── #1333: market_order_reserve_buffer_rate ──────────────


@pytest.mark.asyncio
async def test_market_order_reserve_buffer_rate_db_roundtrip(service):
    """Account 의 market_order_reserve_buffer_rate 가 DB 왕복에서 Decimal 정밀도로
    보존된다 (#1333).
    """
    account = _make_account(
        "buffer-roundtrip",
        market_order_reserve_buffer_rate=Decimal("0.0075"),
    )
    await service.create(account)

    # 캐시 우회: 신규 service 인스턴스로 DB에서 다시 로드.
    svc2 = AccountService(service._db, service._eventbus)
    await svc2.initialize()
    loaded = await svc2.get("buffer-roundtrip")

    assert loaded.market_order_reserve_buffer_rate == Decimal("0.0075")
    assert isinstance(loaded.market_order_reserve_buffer_rate, Decimal)


@pytest.mark.asyncio
async def test_market_order_reserve_buffer_rate_default_zero(service):
    """Account dataclass default 는 Decimal('0') (#1333)."""
    a = _make_account("buffer-default")
    assert a.market_order_reserve_buffer_rate == Decimal("0")


@pytest.mark.asyncio
async def test_market_order_reserve_buffer_rate_blocked_at_runtime_update(
    service,
) -> None:
    """런타임에서 ``market_order_reserve_buffer_rate`` 변경 시도는 cold-path
    409 (``AccountStructuralChangeRequiresStoppedServerError``)로 차단된다 (#1333).
    """
    from ante.account.errors import (
        AccountStructuralChangeRequiresStoppedServerError,
    )

    await service.create(_make_account("buffer-cold-path"))
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
        await service.update(
            "buffer-cold-path",
            market_order_reserve_buffer_rate=Decimal("0.01"),
        )


@pytest.mark.asyncio
async def test_create_default_test_account_uses_preset_buffer(service) -> None:
    """``create_default_test_account`` 가 BrokerPreset 의 buffer(0)를 그대로
    Account 에 반영한다 (#1333).
    """
    acct = await service.create_default_test_account()
    assert acct.market_order_reserve_buffer_rate == Decimal("0")


# ── legacy invalid timezone tolerant load + repair (#1474) ──────────


async def _seed_invalid_timezone_row(
    db,
    *,
    account_id: str = "legacy-tz",
    timezone: str = "Mars/Olympus",
    name: str = "레거시",
    status: str = "active",
) -> None:
    """invalid IANA timezone 으로 DB row 를 직접 삽입하는 helper.

    ``AccountService.create`` 는 ingress 검증 (#1473) 으로 invalid 입력을
    거부하므로, legacy 환경 재현을 위해 raw SQL 로 row 를 심는다. crypto
    credentials 인코딩은 service.create 가 사용하는 ``encrypt_credentials``
    를 재사용해 같은 직렬화 계약을 유지한다 (#1474).
    """
    from datetime import UTC, datetime

    from ante.account.crypto import encrypt_credentials

    now = datetime.now(UTC).isoformat()
    await db.execute(
        """INSERT INTO accounts
           (account_id, name, exchange, currency, timezone,
            trading_hours_start, trading_hours_end, trading_mode,
            broker_type, credentials, broker_config,
            buy_commission_rate, sell_commission_rate,
            market_order_reserve_buffer_rate,
            status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            name,
            "TEST",
            "KRW",
            timezone,
            "09:00",
            "15:30",
            "virtual",
            "test",
            encrypt_credentials({"app_key": "k", "app_secret": "s"}),
            "{}",
            0.0,
            0.0,
            0.0,
            status,
            now,
            now,
        ),
    )


@pytest.mark.asyncio
async def test_load_invalid_timezone_preserves_stored_value_with_marker(
    db, eventbus, caplog
) -> None:
    """legacy invalid timezone row 가 stored value 보존 + marker 로 노출된다 (#1474).

    initialize 가 crash 없이 완료되고, 로드된 Account 의 ``timezone`` 은
    stored ``"Mars/Olympus"`` 그대로 보존된다 — fallback ``"Asia/Seoul"``
    로 덮어쓰면 후속 ``update()`` 의 전체 row UPDATE 가 silent data
    rewrite 를 일으키므로 절대 안 된다.
    """
    import logging

    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    with caplog.at_level(logging.WARNING, logger="ante.account.service"):
        svc2 = AccountService(db, eventbus)
        await svc2.initialize()

    acct = await svc2.get("legacy-tz")
    assert acct.timezone == "Mars/Olympus"
    assert acct.timezone_invalid is True

    messages = [r.getMessage() for r in caplog.records]
    assert any("ACCOUNT_INVALID_TIMEZONE_LEGACY" in m for m in messages)
    assert any("legacy-tz" in m for m in messages)
    assert any("ante account repair-timezone" in m for m in messages)


@pytest.mark.asyncio
async def test_initialize_summary_for_mixed_rows(db, eventbus, caplog) -> None:
    """invalid 와 valid 행이 섞여도 모두 load 되고 summary 한 줄이 남는다 (#1474)."""
    import logging

    svc = AccountService(db, eventbus)
    await svc.initialize()
    await svc.create(_make_account("good-1"))
    await svc.create(_make_account("good-2"))
    await _seed_invalid_timezone_row(db, account_id="bad-a", timezone="Mars/Olympus")
    await _seed_invalid_timezone_row(db, account_id="bad-b", timezone="Foo/Bar")

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ante.account.service"):
        svc2 = AccountService(db, eventbus)
        await svc2.initialize()

    # 모든 4 계좌 load
    assert len(await svc2.list()) == 4

    summary_lines = [
        r.getMessage()
        for r in caplog.records
        if "ACCOUNT_INVALID_TIMEZONE_LEGACY summary" in r.getMessage()
    ]
    assert len(summary_lines) == 1
    summary = summary_lines[0]
    assert "count=2" in summary
    assert "bad-a" in summary
    assert "bad-b" in summary


@pytest.mark.asyncio
async def test_get_non_cached_invalid_row_preserves_marker(db, eventbus) -> None:
    """cache miss 경로(``get`` DB fetch) 에서도 marker 가 유지된다 (#1474).

    invalid row 를 ACTIVE 상태로 심고 service 인스턴스를 새로 만든 뒤
    캐시에 없는 별도의 DELETED row 를 ``get`` 으로 조회하면 DB fetch
    경로(``_row_to_account``) 에서도 stored value + marker 가 그대로
    노출돼야 한다.
    """
    svc = AccountService(db, eventbus)
    await svc.initialize()
    # DELETED 상태 invalid row — initialize 가 캐시에 올리지 않으므로 get()
    # 호출 시 반드시 DB fetch 경로를 탄다.
    await _seed_invalid_timezone_row(
        db, account_id="deleted-tz", timezone="Mars/Olympus", status="deleted"
    )

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()
    assert "deleted-tz" not in svc2._accounts  # cache miss 보장

    acct = await svc2.get("deleted-tz")
    assert acct.timezone == "Mars/Olympus"
    assert acct.timezone_invalid is True
    assert acct.status == AccountStatus.DELETED


@pytest.mark.asyncio
async def test_list_status_deleted_invalid_row_preserves_marker(db, eventbus) -> None:
    """``list(status=DELETED)`` (DB 직접 조회) 경로도 marker 를 보존한다 (#1474)."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(
        db, account_id="deleted-tz", timezone="Mars/Olympus", status="deleted"
    )

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()
    deleted = await svc2.list(status=AccountStatus.DELETED)
    assert len(deleted) == 1
    assert deleted[0].account_id == "deleted-tz"
    assert deleted[0].timezone == "Mars/Olympus"
    assert deleted[0].timezone_invalid is True


@pytest.mark.asyncio
async def test_update_unrelated_field_preserves_invalid_timezone(db, eventbus) -> None:
    """invalid row 의 무관 필드(name) update 시 DB stored timezone 이 보존된다 (#1474).

    silent data rewrite 회귀 회피: 전체 row UPDATE 가 stored
    ``Mars/Olympus`` 를 default 로 덮어쓰면 안 된다.
    """
    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()

    updated = await svc2.update("legacy-tz", name="새 이름")
    assert updated.name == "새 이름"
    assert updated.timezone == "Mars/Olympus"
    assert updated.timezone_invalid is True

    # DB stored value 가 그대로인지 raw 조회로 확인 — 전체 row UPDATE 가
    # ``account.timezone`` (stored) 을 그대로 다시 썼는지 검증.
    row = await db.fetch_one(
        "SELECT timezone FROM accounts WHERE account_id = ?",
        ("legacy-tz",),
    )
    assert row["timezone"] == "Mars/Olympus"

    # 새 service 인스턴스로 다시 로드해도 marker 가 살아 있어야 한다.
    svc3 = AccountService(db, eventbus)
    await svc3.initialize()
    reloaded = await svc3.get("legacy-tz")
    assert reloaded.timezone == "Mars/Olympus"
    assert reloaded.timezone_invalid is True


@pytest.mark.asyncio
async def test_update_timezone_explicit_resets_marker(db, eventbus) -> None:
    """timezone 을 명시적으로 update 하면 marker 가 False 로 리셋된다 (#1474)."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()

    updated = await svc2.update("legacy-tz", timezone="Asia/Tokyo")
    assert updated.timezone == "Asia/Tokyo"
    assert updated.timezone_invalid is False

    row = await db.fetch_one(
        "SELECT timezone FROM accounts WHERE account_id = ?",
        ("legacy-tz",),
    )
    assert row["timezone"] == "Asia/Tokyo"


@pytest.mark.asyncio
async def test_repair_timezone_delegates_to_update(db, eventbus) -> None:
    """``repair_timezone`` 이 ``update(timezone=...)`` 과 동등한 결과를 낸다 (#1474)."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()

    repaired = await svc2.repair_timezone("legacy-tz", "America/New_York")
    assert repaired.timezone == "America/New_York"
    assert repaired.timezone_invalid is False

    row = await db.fetch_one(
        "SELECT timezone FROM accounts WHERE account_id = ?",
        ("legacy-tz",),
    )
    assert row["timezone"] == "America/New_York"


@pytest.mark.asyncio
async def test_repair_timezone_invalid_input_rejected(db, eventbus) -> None:
    """invalid IANA 입력은 ``ValueError`` 로 거부된다 (#1474 — #1473 ingress 재사용)."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()

    with pytest.raises(ValueError, match="invalid IANA timezone"):
        await svc2.repair_timezone("legacy-tz", "Mars/Olympus")

    # DB 의 stored 값이 그대로 보존됐는지 확인.
    row = await db.fetch_one(
        "SELECT timezone FROM accounts WHERE account_id = ?",
        ("legacy-tz",),
    )
    assert row["timezone"] == "Mars/Olympus"


@pytest.mark.asyncio
async def test_repair_timezone_runtime_started_blocked(db, eventbus) -> None:
    """runtime 시작 후에는 cold-path guard 가 즉시 차단한다 (#1474)."""
    from ante.account.errors import (
        AccountStructuralChangeRequiresStoppedServerError,
    )

    svc = AccountService(db, eventbus)
    await svc.initialize()
    await _seed_invalid_timezone_row(db, account_id="legacy-tz")

    svc2 = AccountService(db, eventbus)
    await svc2.initialize()
    svc2.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
        await svc2.repair_timezone("legacy-tz", "Asia/Tokyo")

    # DB 가 변경되지 않았는지 검증.
    row = await db.fetch_one(
        "SELECT timezone FROM accounts WHERE account_id = ?",
        ("legacy-tz",),
    )
    assert row["timezone"] == "Mars/Olympus"
