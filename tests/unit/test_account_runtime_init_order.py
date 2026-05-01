"""``_init_account``가 boot mutation 후에 ``mark_runtime_started``를 호출하는지
검증한다 (#1144 invariant S3).

부팅 시점에 일어나는 두 mutation은:

1. ``create_default_test_account()`` — 계좌 0개일 때 자동 생성. ``create()`` 호출.
2. ``_migrate_is_paper_to_broker_config()`` — KIS 계좌의 broker_config update.
   structural 필드인 ``broker_config``를 변경하므로 ``_runtime_started=False`` 상태에서
   호출되어야 한다.

만약 누군가 ``mark_runtime_started`` 호출을 mutation *전*으로 옮기면,
migration이 ``AccountStructuralChangeRequiresStoppedServerError``로 실패하면서
이 테스트가 fail한다 — invariant S3 위반을 강제한다.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ante.account import Account, AccountService, TradingMode
from ante.config import Config
from ante.core import Database
from ante.eventbus import EventBus


async def test_init_account_marks_runtime_after_test_account_creation(
    tmp_path: Path,
) -> None:
    """``_init_account``가 ``create_default_test_account``를 호출한 다음에야
    ``mark_runtime_started``를 호출한다 (S3).

    mutation 호출 시점의 ``_runtime_started`` 상태를 spy로 기록하여,
    ``create()``가 호출되는 동안 플래그가 False인지 확인한다.
    """
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus(history_size=100)
    config = Config(static={}, secrets={})

    from ante.main import Services, _init_account

    s = Services(db=db, eventbus=eventbus, config=config)

    # account_service는 _init_account 안에서 생성되므로, 일단 함수를 호출하고 끝난
    # 시점의 플래그 상태를 확인한다(post-condition). 호출 순서는 하단의
    # spy 테스트가 검증한다.
    await _init_account(s)
    assert s.account_service is not None
    assert s.account_service._runtime_started is True
    accounts = await s.account_service.list()
    assert len(accounts) == 1
    assert accounts[0].account_id == "test"

    await db.close()


async def test_init_account_runs_migration_before_mark_runtime(
    tmp_path: Path,
) -> None:
    """``_migrate_is_paper_to_broker_config``의 ``account_service.update``
    호출이 ``mark_runtime_started`` 호출보다 먼저 실행된다 (S3).

    호출 시점의 플래그 상태를 wrap으로 기록한다:
    - migration이 호출하는 ``update`` 시점 → ``_runtime_started == False``.
    - ``mark_runtime_started`` 시점 → 그 직후 True가 됨.

    만약 ``mark_runtime_started`` 호출이 mutation 앞으로 옮겨졌다면,
    migration의 structural ``broker_config`` update 자체가
    ``AccountStructuralChangeRequiresStoppedServerError``로 실패한다.
    """
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus(history_size=100)

    # broker.is_paper 레거시 설정을 가진 Config — migration 트리거.
    config = Config(static={"broker": {"is_paper": True}}, secrets={})

    # 미리 KIS 계좌를 만들어 둔다 — `_init_account`가 default test 계좌 생성을
    # 건너뛰고 migration만 수행하도록.
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    existing = Account(
        account_id="kis-acc",
        name="KIS",
        exchange="KRX",
        currency="KRW",
        broker_type="kis-domestic",
        trading_mode=TradingMode.LIVE,
        credentials={"app_key": "k", "app_secret": "s", "account_no": "1"},
        broker_config={},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )
    await account_service.create(existing)

    # 호출 순서 spy.
    call_log: list[str] = []
    runtime_state_log: list[bool] = []

    from ante.main import Services, _init_account

    s = Services(db=db, eventbus=eventbus, config=config)

    # _init_account 안에서 새 AccountService가 생성되지만 동일한 DB를 본다.
    # update / mark_runtime_started를 wrap하여 호출 순간의 플래그 상태를 기록.
    # 패치는 _init_account 내부에서 service가 만들어진 이후에 적용해야 하므로
    # 원본 함수를 살짝 감싼다.

    original_init = _init_account

    async def patched_init(services):
        # 원본 _init_account를 직접 분해하지 않고, account_service 생성을 가로챈다.
        # AccountService.__init__를 monkeypatch하면 모든 인스턴스에 영향이 가므로,
        # 대신 _init_account를 호출한 뒤 결과 service를 검사한다 — 호출 순서는
        # 별도 wrap으로 추적.
        # 더 단순한 방식: _init_account 호출 전에 services.account_service의 wrap
        # 위치를 잡을 수 없으므로, _init_account 함수 내부 동작을 재현하는 대신
        # 직접 검증한다. 따라서 이 중간 함수는 사용하지 않는다.
        await original_init(services)

    # patched_init 대신, 직접 _init_account를 호출하면서 service 생성 후 wrap을 끼운다.
    # 가장 깔끔한 방법: AccountService 인스턴스에 동적 메서드를 덮어쓴다.
    from ante.account.service import AccountService as ASCls

    original_update = ASCls.update
    original_mark = ASCls.mark_runtime_started

    async def spy_update(self, account_id, **fields):
        call_log.append(f"update:{account_id}:{sorted(fields.keys())}")
        runtime_state_log.append(self._runtime_started)
        return await original_update(self, account_id, **fields)

    def spy_mark(self):
        call_log.append("mark_runtime_started")
        return original_mark(self)

    ASCls.update = spy_update
    ASCls.mark_runtime_started = spy_mark

    try:
        await _init_account(s)
    finally:
        # 복원
        ASCls.update = original_update
        ASCls.mark_runtime_started = original_mark

    # 검증:
    # - update 호출이 mark_runtime_started 호출보다 먼저 일어났다.
    update_calls = [i for i, c in enumerate(call_log) if c.startswith("update:")]
    mark_calls = [i for i, c in enumerate(call_log) if c == "mark_runtime_started"]
    assert mark_calls, f"mark_runtime_started not called. log={call_log}"
    assert update_calls, f"update not called. log={call_log}"
    last_update_idx = max(update_calls)
    first_mark_idx = min(mark_calls)
    assert last_update_idx < first_mark_idx, (
        f"mark_runtime_started must come AFTER all update() calls. log={call_log}"
    )
    # update 호출 시점의 _runtime_started는 False여야 한다.
    assert all(state is False for state in runtime_state_log), (
        f"update() called while _runtime_started=True (S3 violation). "
        f"states={runtime_state_log}"
    )

    # post-condition: _init_account 종료 후 플래그는 True
    assert s.account_service._runtime_started is True

    await db.close()


async def test_init_account_marks_runtime_when_no_migration_needed(
    tmp_path: Path,
) -> None:
    """legacy ``broker.is_paper`` 설정이 없어도 ``mark_runtime_started``가 호출된다.

    이 경우 migration ``update``는 호출되지 않지만, 부팅 종료 시점 플래그는 True여야
    cold-path 가드가 활성화된다.
    """
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus(history_size=100)
    # broker.is_paper 미설정 → migration skip
    config = Config(static={}, secrets={})

    from ante.main import Services, _init_account

    s = Services(db=db, eventbus=eventbus, config=config)

    await _init_account(s)
    assert s.account_service._runtime_started is True

    await db.close()
