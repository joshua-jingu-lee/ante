"""AccountService runtime guard 테스트 (#1144).

S1-S5 invariant 검증:

- S1: ``_runtime_started`` 기본값 False, ``mark_runtime_started`` 멱등.
- S2: ``create()``/``update()``/``delete()`` 가드가 다른 모든 검사보다 먼저 평가.
- S3: 부팅 mutation은 플래그 활성 전에 실행
  (``test_account_runtime_init_order.py``에서 보강).
- S4: service ``STRUCTURAL_FIELDS`` ↔ route ``STRUCTURAL_FIELDS`` 1:1 정합.
- S5: 새 예외의 ``code`` 클래스 속성 노출.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from ante.account.errors import (
    AccountDeletedError,
    AccountNotFoundError,
    AccountStructuralChangeRequiresStoppedServerError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.service import STRUCTURAL_FIELDS, AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db_path = str(tmp_path / "runtime_guard.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest_asyncio.fixture
async def service(db, eventbus):
    """초기화된 AccountService — `_runtime_started`는 False."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    return svc


def _make_account(account_id: str = "test", broker_type: str = "test") -> Account:
    """테스트용 기본 Account."""
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        broker_type=broker_type,
        credentials={"app_key": "test", "app_secret": "test"},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
    )


# ── S1: 기본 플래그 / 멱등 ──────────────────────────


def test_runtime_flag_default_false(service: AccountService) -> None:
    """신규 AccountService 인스턴스의 ``_runtime_started``는 False (S1)."""
    assert service._runtime_started is False


def test_mark_runtime_started_is_idempotent(service: AccountService) -> None:
    """``mark_runtime_started()``는 멱등 — 두 번 호출해도 True 유지, 예외 없음 (S1)."""
    assert service._runtime_started is False
    service.mark_runtime_started()
    assert service._runtime_started is True
    # 두 번째 호출도 no-op로 통과 + True 유지.
    service.mark_runtime_started()
    assert service._runtime_started is True


# ── S2: create()/delete() 런타임 차단 + code 검증 ────


@pytest.mark.asyncio
async def test_create_blocked_after_mark_runtime_started(
    service: AccountService,
) -> None:
    """``create()`` 첫 줄에서 cold-path 가드가 raise한다 (S2/S5)."""
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError) as exc_info:
        await service.create(_make_account("new-account"))

    assert exc_info.value.code == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


@pytest.mark.asyncio
async def test_delete_blocked_after_mark_runtime_started(
    service: AccountService,
) -> None:
    """``delete()`` 첫 줄에서 cold-path 가드가 raise한다 (S2/S5)."""
    # 먼저 cold-path 시점에 계좌 하나 만들어둔다.
    await service.create(_make_account("victim"))
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError) as exc_info:
        await service.delete("victim", deleted_by="tester")

    assert exc_info.value.code == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


# ── S2: update() 런타임 차단 (8필드 파라미터화) ───────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("credentials", {"app_key": "x", "app_secret": "y"}),
        ("broker_config", {"is_paper": True}),
        ("buy_commission_rate", Decimal("0.001")),
        ("sell_commission_rate", Decimal("0.002")),
        ("broker_type", "kis-domestic"),
        ("exchange", "KRX"),
        ("currency", "USD"),
        ("trading_mode", TradingMode.LIVE),
    ],
)
async def test_update_structural_blocked_after_mark_runtime_started(
    service: AccountService,
    field: str,
    value,
) -> None:
    """``update()``에 structural 키가 들어오면 가드가 차단한다 (S2). 8필드 모두."""
    await service.create(_make_account("victim"))
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError) as exc_info:
        await service.update("victim", **{field: value})

    # 메시지에 어떤 필드가 차단됐는지 노출
    assert field in str(exc_info.value)
    assert exc_info.value.code == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


@pytest.mark.asyncio
async def test_update_structural_with_null_value_blocked(
    service: AccountService,
) -> None:
    """``update(account_id, credentials=None)``도 키 존재만으로 raise (S2).

    가드는 raw kwargs 키만 보고 값(None 포함)은 무관하다 — invariant I4와 대칭.
    """
    await service.create(_make_account("victim"))
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
        await service.update("victim", credentials=None)


@pytest.mark.asyncio
async def test_update_structural_blocks_before_get(service: AccountService) -> None:
    """존재하지 않는 account_id에 structural 키 → cold-path 가드가 우선 (S2).

    가드는 ``get()`` 호출 *전*에 평가되므로 ``AccountNotFoundError``보다 먼저
    ``AccountStructuralChangeRequiresStoppedServerError``가 raise된다.
    """
    service.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
        await service.update(
            "nonexistent-account", credentials={"app_key": "x", "app_secret": "y"}
        )


@pytest.mark.asyncio
async def test_update_structural_blocks_on_deleted_account(db, eventbus) -> None:
    """DELETED 상태 계좌에 structural 키 → cold-path 가드가 우선 (S2).

    ``AccountDeletedError``보다 먼저 cold-path 예외가 raise된다. DELETED
    상태 계좌는 메모리 캐시에 없고 DB에만 있으므로 해당 상황을 직접 구성한다.
    """
    svc = AccountService(db, eventbus)
    await svc.initialize()

    # cold-path에서 생성 후 삭제 → DB에는 DELETED 상태로 남는다.
    await svc.create(_make_account("victim"))
    await svc.delete("victim", deleted_by="setup")

    # runtime 활성화 후 structural 키로 update 시도.
    svc.mark_runtime_started()

    with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
        await svc.update("victim", credentials={"app_key": "x", "app_secret": "y"})


@pytest.mark.asyncio
async def test_update_mutable_only_succeeds_after_mark_runtime_started(
    service: AccountService,
) -> None:
    """mutable-only 호출(name, timezone 등)은 runtime에서도 정상 동작 (S2).

    가드는 STRUCTURAL_FIELDS와 키 교집합이 있을 때만 차단한다.
    """
    await service.create(_make_account("victim"))
    service.mark_runtime_started()

    updated = await service.update(
        "victim",
        name="새 이름",
        timezone="America/New_York",
        trading_hours_start="09:30",
        trading_hours_end="16:00",
    )
    assert updated.name == "새 이름"
    assert updated.timezone == "America/New_York"
    assert updated.trading_hours_start == "09:30"
    assert updated.trading_hours_end == "16:00"


# ── S3: 부팅 시점 mutation은 raise 없이 성공 ─────────


@pytest.mark.asyncio
async def test_create_default_test_account_succeeds_before_mark_runtime(
    service: AccountService,
) -> None:
    """pre-runtime boot 시나리오에서 ``create_default_test_account``가 동작한다.

    ``mark_runtime_started`` 호출 전이므로 ``create()`` 가드가 통과한다 (S3).
    """
    assert service._runtime_started is False

    account = await service.create_default_test_account()
    assert account.account_id == "test"
    assert account.broker_type == "test"


# ── S4: service STRUCTURAL_FIELDS ↔ route STRUCTURAL_FIELDS 정합 ────


def test_structural_fields_match_route_constant() -> None:
    """service의 ``STRUCTURAL_FIELDS``와 route의 ``STRUCTURAL_FIELDS``가
    정확히 일치 (S4 contract-drift 방지).
    """
    from ante.web.routes.accounts import STRUCTURAL_FIELDS as ROUTE_FIELDS

    # route는 tuple, service는 frozenset이지만 set 비교로 동일 멤버를 강제.
    assert set(ROUTE_FIELDS) == set(STRUCTURAL_FIELDS)
    # 8필드 정확히 일치
    assert len(set(ROUTE_FIELDS)) == 8
    assert len(STRUCTURAL_FIELDS) == 8


def test_structural_fields_matches_spec() -> None:
    """spec에 명시된 8필드와 service ``STRUCTURAL_FIELDS``가 정확히 일치.

    spec SSOT: docs/specs/account/04-account-service.md 51-58줄.
    """
    expected = {
        "credentials",
        "broker_config",
        "buy_commission_rate",
        "sell_commission_rate",
        "broker_type",
        "exchange",
        "currency",
        "trading_mode",
    }
    assert set(STRUCTURAL_FIELDS) == expected


# ── S5: 새 예외 인스턴스 code 검증 ────────────────────


def test_account_structural_change_error_carries_stable_code() -> None:
    """``AccountStructuralChangeRequiresStoppedServerError`` 인스턴스의 ``code``
    클래스 속성이 안정 코드를 노출한다 (S5).
    """
    exc = AccountStructuralChangeRequiresStoppedServerError("test message")
    assert exc.code == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
    # 클래스 레벨 속성으로도 접근 가능 (IPCServer ``getattr(e, "code", ...)`` 호환)
    assert (
        AccountStructuralChangeRequiresStoppedServerError.code
        == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
    )


# ── 회귀 보호: 정상 mutable 흐름이 깨지지 않는지 ────


@pytest.mark.asyncio
async def test_pre_runtime_create_update_delete_works(
    service: AccountService,
) -> None:
    """pre-runtime 시점에는 create/update/delete 모두 정상 동작 (S3 검증)."""
    assert service._runtime_started is False

    # cold-path create
    await service.create(_make_account("victim"))

    # cold-path structural update (credentials 변경)
    updated = await service.update(
        "victim",
        credentials={"app_key": "new", "app_secret": "new"},
    )
    assert updated.credentials == {"app_key": "new", "app_secret": "new"}

    # cold-path delete
    await service.delete("victim", deleted_by="tester")

    # 캐시에서 사라졌는지
    fetched = await service.get("victim")
    assert fetched.status == AccountStatus.DELETED


@pytest.mark.asyncio
async def test_update_nonexistent_pre_runtime_still_raises_not_found(
    service: AccountService,
) -> None:
    """pre-runtime에 존재하지 않는 account_id에 structural 키 → 정상 not-found.

    가드가 활성화되지 않았을 때는 기존 동작(get → ``AccountNotFoundError``)이
    유지된다.
    """
    assert service._runtime_started is False

    with pytest.raises(AccountNotFoundError):
        await service.update(
            "nonexistent", credentials={"app_key": "x", "app_secret": "y"}
        )


@pytest.mark.asyncio
async def test_update_deleted_pre_runtime_still_raises_deleted(db, eventbus) -> None:
    """pre-runtime에 DELETED 계좌 structural 키 → 정상 ``AccountDeletedError``."""
    svc = AccountService(db, eventbus)
    await svc.initialize()

    await svc.create(_make_account("victim"))
    await svc.delete("victim", deleted_by="setup")

    # mark_runtime_started 호출 안 함 → 가드 비활성

    with pytest.raises(AccountDeletedError):
        await svc.update("victim", credentials={"app_key": "x", "app_secret": "y"})
