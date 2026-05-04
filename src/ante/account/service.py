"""AccountService — 계좌 CRUD 및 상태 관리."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ante.account.crypto import decrypt_credentials, encrypt_credentials
from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountDeletedException,
    AccountHasActiveBotsError,
    AccountImmutableFieldError,
    AccountNotFoundError,
    AccountStructuralChangeRequiresStoppedServerError,
    BrokerReconnectFailedError,
    InvalidAccountIdError,
    InvalidBrokerTypeError,
    MissingCredentialsError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.presets import BROKER_PRESETS
from ante.account.scoping import require_account_id, validate_new_account_id

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# 브로커 어댑터 레지스트리 — broker_type → 어댑터 클래스
_BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {}

# AccountService.list 메서드명이 클래스 내부 후속 메서드의 ``list[...]`` 어노테이션과
# mypy 평가 시점에 충돌하므로(``Function "AccountService.list" is not valid as a type``)
# 모듈 스코프에서 builtin ``list``를 캡처한 alias를 사용한다.
_AccountStatusReport = list[dict[str, Any]]

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS accounts (
    account_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    exchange     TEXT NOT NULL,
    currency     TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT 'Asia/Seoul',
    trading_hours_start TEXT NOT NULL DEFAULT '09:00',
    trading_hours_end   TEXT NOT NULL DEFAULT '15:30',
    trading_mode TEXT NOT NULL DEFAULT 'virtual'
        CHECK(trading_mode IN ('virtual', 'live')),
    broker_type  TEXT NOT NULL,
    credentials  TEXT NOT NULL DEFAULT '{}',
    broker_config TEXT NOT NULL DEFAULT '{}',
    buy_commission_rate  REAL NOT NULL DEFAULT 0,
    sell_commission_rate REAL NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'suspended', 'deleted')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _register_brokers() -> None:
    """브로커 어댑터를 lazy 등록한다.

    순환 import 방지를 위해 최초 호출 시 import한다.
    """
    if _BROKER_REGISTRY:
        return

    from ante.broker.kis import KISAdapter
    from ante.broker.test import TestBrokerAdapter

    _BROKER_REGISTRY["test"] = TestBrokerAdapter
    _BROKER_REGISTRY["kis-domestic"] = KISAdapter


# Cold-path 전용 필드 (서버 실행 중에는 변경 불가).
# SSOT:
#   - docs/specs/account/04-account-service.md 51-58줄
#   - src/ante/web/routes/accounts.py STRUCTURAL_FIELDS (8개 라우트 1차 가드)
#
# - credentials, broker_config, buy_commission_rate, sell_commission_rate:
#   broker adapter 재초기화가 필요한 필드.
# - exchange, currency, trading_mode, broker_type:
#   계좌 생성 후 불변 필드 (구조 변경 시 모든 소비자 재구성 필요).
#
# 두 set이 어긋나면 contract-drift이므로 cross-import 테스트
# (test_account_runtime_guard.test_structural_fields_match_route_constant)로 강제한다.
STRUCTURAL_FIELDS: frozenset[str] = frozenset(
    {
        "credentials",
        "broker_config",
        "buy_commission_rate",
        "sell_commission_rate",
        "broker_type",
        "exchange",
        "currency",
        "trading_mode",
    }
)


class AccountService:
    """계좌 CRUD, 상태 관리, 브로커 인스턴스 생성."""

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus
        self._accounts: dict[str, Account] = {}
        self._brokers: dict[str, BrokerAdapter] = {}
        # 런타임 인지 플래그(#1144 invariant S1).
        # boot mutation 종료 직후(``main._init_account`` 마지막)
        # ``mark_runtime_started()``로 True가 되며, 이후 cold-path 전용 메서드/필드
        # 변경 요청을 ``AccountStructuralChangeRequiresStoppedServerError``로
        # 즉시 차단한다.
        self._runtime_started: bool = False

    def mark_runtime_started(self) -> None:
        """서버 부팅 mutation을 모두 마쳤음을 표시한다 (#1144 invariant S1/S3).

        이 호출 이후로 ``create()``, ``delete()``, structural 키를 포함한
        ``update()`` 호출은 ``AccountStructuralChangeRequiresStoppedServerError``로
        즉시 차단된다 — DB는 수정되지 않는다.

        멱등: 이미 True 상태에서 호출하면 no-op.
        """
        self._runtime_started = True

    # ── 초기화 ──────────────────────────────────────────

    async def initialize(self) -> None:
        """스키마 생성 + DB에서 계좌 목록 로드."""
        await self._db.execute_script(_CREATE_TABLE_SQL)
        rows = await self._db.fetch_all(
            "SELECT * FROM accounts WHERE status != ?",
            (AccountStatus.DELETED,),
        )
        for row in rows:
            account = _row_to_account(row)
            self._accounts[account.account_id] = account
        logger.info("AccountService 초기화 완료: %d개 계좌 로드", len(self._accounts))

    # ── CRUD ──────────────────────────────────────────

    async def create(self, account: Account) -> Account:
        """계좌 생성. **cold-path 전용**.

        모든 public 호출자(CLI ``ante account create``, web POST 라우트, IPC
        등)는 ``account_id`` 정책 검증( :func:`validate_new_account_id` )을 반드시
        통과해야 한다. RESTRICTED seed 예약어( ``"test"`` )와 fallback 예약어
        ( ``"default"`` )는 이 경로에서 우회 수단 없이 차단된다. Bootstrap seed
        계좌 자동 생성은 별도의 private helper :meth:`_create_seed_account`
        (only invoked by :meth:`create_default_test_account`) 가 담당한다 —
        public ``create()`` API에는 우회 플래그를 노출하지 않는다 (#1216 P2).

        Args:
            account: 생성할 계좌 정보.

        Returns:
            생성된 Account (created_at, updated_at 포함).

        Raises:
            AccountStructuralChangeRequiresStoppedServerError: 서버 실행 중
                호출됨. 다른 어떤 검사보다 먼저 평가된다 (#1144 invariant S2).
            AccountAlreadyExistsError: 동일 account_id가 이미 존재.
            InvalidAccountIdError: account_id 형식이 올바르지 않거나
                ``RESTRICTED_NEW_ACCOUNT_IDS`` ( ``"test"`` ) /
                ``INVALID_RUNTIME_ACCOUNT_IDS`` ( ``"default"`` ) 예약어와
                일치하는 경우.
            InvalidBrokerTypeError: broker_type이 프리셋에 정의되지 않음.
            MissingCredentialsError: 필수 credentials 키 누락.
        """
        # 런타임 cold-path 가드(invariant S2): 다른 어떤 검사보다 먼저 평가.
        self._guard_cold_path_create()

        # account_id 형식 + 정책 검증.
        # public 경로는 validate_new_account_id로 형식 + RESTRICTED + fallback
        # 거부를 모두 강제한다. seed bootstrap은 _create_seed_account를 통해서만
        # 가능하며 그 helper가 별도의 (broker_type, default_account_id) pair
        # 가드를 적용한다 (#1216 P2).
        # docs/specs/account/14-account-id-contract.md 참조.
        validate_new_account_id(account.account_id)

        return await self._persist_account(account)

    async def _create_seed_account(self, account: Account) -> Account:
        """Bootstrap seed 계좌 생성 (**private**).

        :meth:`create_default_test_account` 전용 진입점. public ``create()`` API
        에 ``_bootstrap`` 플래그를 노출하지 않기 위해 별도 private helper로
        캡슐화한다. ``broker_type`` 과 ``account_id`` 가 ``BROKER_PRESETS`` 의
        동일 항목에서 정의된 ``(broker_type, default_account_id)`` pair와
        정확히 일치할 때만 허용한다 — 한 preset의 ``default_account_id`` 를 다른
        preset의 ``broker_type`` 아래로 끼워 넣어 RESTRICTED 예약어( ``"test"`` )
        를 비-test broker 아래에 저장하는 우회를 막는다 (#1216 P2).

        형식 검증( :func:`require_account_id` )은 ``BROKER_PRESETS`` 자체가 잘못
        변경되는 경우에 대비한 추가 가드로 적용한다. cold-path 가드와 broker_type
        / credentials 검증 / DB insert는 public ``create()`` 와 동일한 조건을
        적용한다 ( :meth:`_persist_account` 공유).

        Raises:
            AccountStructuralChangeRequiresStoppedServerError: 서버 실행 중
                호출됨 (invariant S2).
            InvalidAccountIdError: ``(broker_type, account_id)`` 가
                ``BROKER_PRESETS`` 의 어느 ``(broker_type, default_account_id)``
                pair와도 일치하지 않거나, pair는 일치해도 형식 위반인 경우.
            AccountAlreadyExistsError, InvalidBrokerTypeError,
            MissingCredentialsError: :meth:`_persist_account` 와 동일.
        """
        # 런타임 cold-path 가드(invariant S2): 다른 어떤 검사보다 먼저 평가.
        self._guard_cold_path_create()

        # (broker_type, default_account_id) pair 가드 — RESTRICTED 예약어가
        # 다른 preset의 broker_type 아래로 새는 것을 차단한다 (#1216 P2).
        preset = BROKER_PRESETS.get(account.broker_type)
        if preset is None or preset.default_account_id != account.account_id:
            valid_pairs = [
                (bt, p.default_account_id) for bt, p in BROKER_PRESETS.items()
            ]
            raise InvalidAccountIdError(
                f"seed 계좌 생성은 (broker_type, default_account_id) pair만 "
                f"허용합니다: got broker_type={account.broker_type!r}, "
                f"account_id={account.account_id!r}; valid pairs={valid_pairs}"
            )
        # pair 일치해도 형식 검증은 그대로
        # (BROKER_PRESETS가 잘못 변경되더라도 가드).
        require_account_id(account.account_id, context="bootstrap_seed")

        return await self._persist_account(account)

    def _guard_cold_path_create(self) -> None:
        """``create*()`` 진입 시 런타임 cold-path 가드 (invariant S2).

        ``create()`` 와 ``_create_seed_account()`` 가 동일 메시지/예외 의미론으로
        가장 먼저 평가하기 위한 공유 helper.
        """
        if self._runtime_started:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "계좌 생성은 cold-path 전용입니다. "
                "서버를 정지한 뒤 ante account create로 수행하세요."
            )

    async def _persist_account(self, account: Account) -> Account:
        """``account_id`` 검증 이후 공통 검증 + DB insert (private helper).

        ``create()`` 와 ``_create_seed_account()`` 가 공유한다. 진입 전 호출자가
        이미 ``_guard_cold_path_create()`` 와 account_id 정책 검증을 끝냈다고
        가정한다 — 이 helper는 ``account_id`` 정책에 대해서는 어떤 가드도
        적용하지 않는다.

        Raises:
            AccountAlreadyExistsError: 동일 account_id가 메모리/DELETED DB
                상태로 이미 존재.
            InvalidBrokerTypeError: broker_type이 프리셋에 정의되지 않음.
            MissingCredentialsError: 필수 credentials 키 누락.
        """
        if account.account_id in self._accounts:
            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다."
            )

        # DB에서 soft-delete된 동일 ID 존재 여부 확인
        deleted = await self._db.fetch_one(
            "SELECT account_id FROM accounts WHERE account_id = ? AND status = ?",
            (account.account_id, AccountStatus.DELETED),
        )
        if deleted:
            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다 (삭제 상태)."
            )

        # broker_type 유효성 검증 (프리셋에 정의된 것만 허용)
        if account.broker_type not in BROKER_PRESETS:
            raise InvalidBrokerTypeError(
                f"유효하지 않은 broker_type: '{account.broker_type}'. "
                f"가능한 값: {list(BROKER_PRESETS.keys())}"
            )

        # credentials 필수 키 검증
        preset = BROKER_PRESETS[account.broker_type]
        missing = [
            k for k in preset.required_credentials if k not in account.credentials
        ]
        if missing:
            raise MissingCredentialsError(
                f"필수 credentials 누락: {missing}. "
                f"broker_type '{account.broker_type}'에 필요: "
                f"{preset.required_credentials}"
            )

        now = datetime.now(UTC)
        account.created_at = now
        account.updated_at = now

        await self._db.execute(
            """INSERT INTO accounts
               (account_id, name, exchange, currency, timezone,
                trading_hours_start, trading_hours_end, trading_mode,
                broker_type, credentials, broker_config,
                buy_commission_rate, sell_commission_rate,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account.account_id,
                account.name,
                account.exchange,
                account.currency,
                account.timezone,
                account.trading_hours_start,
                account.trading_hours_end,
                account.trading_mode.value,
                account.broker_type,
                encrypt_credentials(account.credentials),
                json.dumps(account.broker_config),
                float(account.buy_commission_rate),
                float(account.sell_commission_rate),
                account.status.value,
                now.isoformat(),
                now.isoformat(),
            ),
        )

        self._accounts[account.account_id] = account
        logger.info(
            "계좌 생성: %s (%s/%s)",
            account.account_id,
            account.exchange,
            account.broker_type,
        )
        return account

    async def get(self, account_id: str) -> Account:
        """계좌 조회. DELETED 상태도 조회 가능.

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
        """
        # 메모리 캐시에서 먼저 검색
        if account_id in self._accounts:
            return self._accounts[account_id]

        # DELETED 계좌는 메모리에 없으므로 DB에서 검색
        row = await self._db.fetch_one(
            "SELECT * FROM accounts WHERE account_id = ?",
            (account_id,),
        )
        if row is None:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return _row_to_account(row)

    def get_sync(self, account_id: str) -> Account | None:
        """동기 캐시 조회. 인메모리에 있는 계좌만 반환, 없으면 None.

        ContextFactory 등 동기 컨텍스트에서 사용한다.
        """
        return self._accounts.get(account_id)

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        """계좌 목록 조회. DELETED 제외가 기본."""
        if status is not None:
            if status == AccountStatus.DELETED:
                # DELETED는 DB에서 직접 조회
                rows = await self._db.fetch_all(
                    "SELECT * FROM accounts WHERE status = ?",
                    (AccountStatus.DELETED,),
                )
                return [_row_to_account(row) for row in rows]
            return [a for a in self._accounts.values() if a.status == status]
        # 기본: DELETED 제외 (메모리 캐시에는 DELETED가 없음)
        return list(self._accounts.values())

    # 생성 후 변경 불가능한 필드
    IMMUTABLE_FIELDS: frozenset[str] = frozenset(
        {"exchange", "currency", "trading_mode", "broker_type"}
    )

    async def update(self, account_id: str, **fields: Any) -> Account:
        """계좌 부분 수정. updated_at 자동 갱신.

        런타임에서는 비구조 필드(``name``, ``timezone``, ``trading_hours_start``,
        ``trading_hours_end``)만 변경할 수 있다. ``STRUCTURAL_FIELDS`` 중
        하나라도 키로 등장하면(값이 ``None``이어도) cold-path 위반으로 판단,
        ``AccountStructuralChangeRequiresStoppedServerError``를 raise한다 — DB
        조회를 수행하지 않으므로 nonexistent/DELETED 계좌도 cold-path 응답이
        우선이다 (#1144 invariant S2).

        Raises:
            AccountStructuralChangeRequiresStoppedServerError: 서버 실행 중
                structural 키 변경 시도. ``get()``/DELETED/IMMUTABLE 등 다른
                모든 검사보다 먼저 평가된다 (invariant S2).
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: DELETED 계좌는 수정 불가.
            AccountImmutableFieldError: 불변 필드 수정 시도.
        """
        # 런타임 cold-path 가드(invariant S2): get()/DELETED/IMMUTABLE 검사보다
        # 먼저 평가한다. raw kwargs 키만 보고 값(None 포함)은 무관하다.
        if self._runtime_started:
            structural_hits = sorted(set(fields) & STRUCTURAL_FIELDS)
            if structural_hits:
                raise AccountStructuralChangeRequiresStoppedServerError(
                    f"다음 필드는 cold-path 전용입니다: {', '.join(structural_hits)}"
                )

        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )

        # 불변 필드 수정 시도 차단
        attempted_immutable = set(fields.keys()) & self.IMMUTABLE_FIELDS
        if attempted_immutable:
            raise AccountImmutableFieldError(
                f"다음 필드는 수정할 수 없습니다: {sorted(attempted_immutable)}"
            )

        updatable = {
            "name",
            "timezone",
            "trading_hours_start",
            "trading_hours_end",
            "credentials",
            "broker_config",
            "buy_commission_rate",
            "sell_commission_rate",
        }
        unrecognized = set(fields.keys()) - updatable - self.IMMUTABLE_FIELDS
        if unrecognized:
            raise ValueError(f"인식할 수 없는 필드입니다: {sorted(unrecognized)}")
        broker_invalidating = {
            "credentials",
            "broker_config",
            "buy_commission_rate",
            "sell_commission_rate",
        }
        invalidate_broker = bool(set(fields.keys()) & broker_invalidating)
        for key, value in fields.items():
            if key not in updatable:
                continue
            setattr(account, key, value)

        now = datetime.now(UTC)
        account.updated_at = now

        await self._db.execute(
            """UPDATE accounts SET
               name=?, exchange=?, currency=?, timezone=?,
               trading_hours_start=?, trading_hours_end=?, trading_mode=?,
               broker_type=?, credentials=?, broker_config=?,
               buy_commission_rate=?, sell_commission_rate=?,
               updated_at=?
               WHERE account_id=?""",
            (
                account.name,
                account.exchange,
                account.currency,
                account.timezone,
                account.trading_hours_start,
                account.trading_hours_end,
                account.trading_mode.value,
                account.broker_type,
                encrypt_credentials(account.credentials),
                json.dumps(account.broker_config),
                float(account.buy_commission_rate),
                float(account.sell_commission_rate),
                now.isoformat(),
                account_id,
            ),
        )

        self._accounts[account_id] = account
        if invalidate_broker:
            await self._reconnect_broker(account_id)
        logger.info("계좌 수정: %s", account_id)
        return account

    async def _reconnect_broker(self, account_id: str) -> None:
        """새 브로커 어댑터를 생성·연결한 뒤에만 캐시를 교체한다.

        update()에서 credentials/broker_config/수수료율 등 브로커 재생성이
        필요한 필드가 바뀐 직후 호출된다.

        캐시가 비어 있으면 아무 것도 하지 않는다. 재연결은 이미 런타임에
        생성돼 있는 어댑터를 새 설정으로 교체하는 작업이므로, 캐시 부재
        시점(예: 부팅 중 레거시 is_paper 마이그레이션처럼 아직 `get_broker()`가
        불린 적 없는 구간)에는 의미가 없고, 다음 `get_broker()` 호출이 새
        설정으로 lazy init한다.

        실패 의미론:
        - 새 어댑터 생성(`_build_broker_adapter`) 실패 → 캐시는 기존 브로커를
          그대로 유지하고, `BrokerReconnectFailedError`를 올려 update() 호출자가
          DB는 갱신됐으나 런타임 브로커는 구 설정임을 인지하게 한다.
        - 새 어댑터 connect() 실패 → 동일하게 기존 캐시를 보존하고
          `BrokerReconnectFailedError`를 올린다. 캐시에 `is_connected=False`인
          stale 어댑터가 남아 후속 gateway 호출을 계속 깨뜨리는 회귀를 막는다.
        - 새 어댑터가 성공적으로 connect된 뒤에야 캐시를 원자적으로 교체한다.

        **이전 어댑터는 의도적으로 disconnect하지 않는다.** `ReconcileScheduler`나
        `Treasury.start_sync()` 같은 장기 실행 consumer가 시작 시점에 주입받은
        BrokerAdapter 참조를 내부에 고정해서 사용하기 때문이다. 새 어댑터로
        캐시를 교체하면 `AccountService.get_broker()` / `APIGateway` 경로는
        즉시 새 설정을 사용하지만, 이미 시작된 consumer는 참조를 통해 구
        어댑터를 계속 사용한다. 구 어댑터를 세션 레벨까지 끊어버리면 주기
        대사/잔고 동기화가 바로 깨지므로, 구 어댑터는 자연스러운 GC와 서비스
        재시작 시점까지 살려둔다. consumer에 새 어댑터를 주입하는 이벤트
        기반 경로는 후속 작업으로 분리한다 (#1100의 범위를 넘어선다).
        """
        if account_id not in self._brokers:
            return

        try:
            new_broker = await self._build_broker_adapter(account_id)
        except Exception as exc:
            logger.error(
                "브로커 어댑터 생성 실패: account=%s — 기존 캐시를 유지합니다.",
                account_id,
                exc_info=True,
            )
            raise BrokerReconnectFailedError(
                f"계좌 '{account_id}'의 새 브로커 어댑터 생성에 실패했습니다."
            ) from exc

        try:
            await new_broker.connect()
        except Exception as exc:
            logger.error(
                "브로커 재연결 실패: account=%s — 기존 캐시를 유지합니다.",
                account_id,
                exc_info=True,
            )
            raise BrokerReconnectFailedError(
                f"계좌 '{account_id}'의 새 브로커 connect()에 실패했습니다."
            ) from exc

        # connect 성공 후에만 캐시를 원자적으로 교체한다.
        # 이전 어댑터는 의도적으로 disconnect하지 않는다 (docstring 참고).
        self._brokers[account_id] = new_broker

    # ── 상태 전이 ──────────────────────────────────────

    async def suspend(self, account_id: str, reason: str, suspended_by: str) -> None:
        """계좌 정지 (status -> SUSPENDED).

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: 삭제된 계좌.
        """
        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(
                f"삭제된 계좌 '{account_id}'는 정지할 수 없습니다."
            )
        if account.status == AccountStatus.SUSPENDED:
            from ante.account.errors import AccountAlreadySuspendedError

            raise AccountAlreadySuspendedError(
                f"이미 정지된 계좌입니다: '{account_id}'"
            )
        account.status = AccountStatus.SUSPENDED
        account.updated_at = datetime.now(UTC)

        await self._db.execute(
            "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
            (AccountStatus.SUSPENDED, account.updated_at.isoformat(), account_id),
        )

        from ante.eventbus.events import AccountSuspendedEvent

        await self._eventbus.publish(
            AccountSuspendedEvent(
                account_id=account_id,
                reason=reason,
                suspended_by=suspended_by,
            )
        )

        logger.info(
            "계좌 정지: %s (사유: %s, 요청자: %s)",
            account_id,
            reason,
            suspended_by,
        )

    async def activate(self, account_id: str, activated_by: str) -> None:
        """계좌 활성화 (status -> ACTIVE).

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: DELETED 계좌는 활성화 불가.
        """
        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(
                f"삭제된 계좌 '{account_id}'는 활성화할 수 없습니다."
            )
        if account.status == AccountStatus.ACTIVE:
            return

        account.status = AccountStatus.ACTIVE
        account.updated_at = datetime.now(UTC)

        await self._db.execute(
            "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
            (AccountStatus.ACTIVE, account.updated_at.isoformat(), account_id),
        )

        from ante.eventbus.events import AccountActivatedEvent

        await self._eventbus.publish(
            AccountActivatedEvent(
                account_id=account_id,
                activated_by=activated_by,
            )
        )

        logger.info("계좌 활성화: %s (요청자: %s)", account_id, activated_by)

    async def delete(self, account_id: str, deleted_by: str) -> None:
        """소프트 딜리트 (status -> DELETED). cold-path 전용.

        진입 직후 ``bots`` 테이블을 검사하여 active(non-deleted) 봇이 남아 있으면
        ``AccountHasActiveBotsError``를 raise한다 (#1139, orphan bot 무결성).
        ``bots`` 테이블 자체가 없으면(BotManager 미초기화 환경) active 봇이
        없는 것으로 간주한다.

        1.0 EventBus 계약: ``AccountDeletedEvent``는 발행하지 않는다. cold-path
        delete는 consumer wiring을 트리거하지 않는다. ``AccountSuspendedEvent``
        (reason="Account deletion")는 BotManager가 소속 봇을 중지시키도록 유지한다.

        Raises:
            AccountStructuralChangeRequiresStoppedServerError: 서버 실행 중
                호출됨. 다른 어떤 검사보다 먼저 평가된다 (#1144 invariant S2).
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: 이미 삭제된 계좌.
            AccountHasActiveBotsError: 활성(non-deleted) 봇이 남아 있음.
        """
        # 런타임 cold-path 가드(invariant S2): 다른 어떤 검사보다 먼저 평가.
        if self._runtime_started:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "계좌 삭제는 cold-path 전용입니다. "
                "서버를 정지한 뒤 ante account delete로 수행하세요."
            )

        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(f"이미 삭제된 계좌입니다: '{account_id}'")

        # cold-path preflight: orphan bot 무결성 검사.
        # bots 테이블이 없으면 active 봇이 없는 것으로 간주.
        active_bot_count = await self._count_active_bots(account_id)
        if active_bot_count > 0:
            raise AccountHasActiveBotsError(
                account_id=account_id, bot_count=active_bot_count
            )

        # 소속 봇 중지 트리거 (이미 SUSPENDED/DELETED면 스킵).
        # 봇이 없는 정상 흐름에서는 사실상 no-op이지만, 봇 중지 시점과 cold-path
        # delete 사이의 race로 잔존 ACTIVE 상태 consumer가 있을 가능성에 대비해
        # 유지한다.
        if account.status not in (AccountStatus.SUSPENDED, AccountStatus.DELETED):
            from ante.eventbus.events import AccountSuspendedEvent

            await self._eventbus.publish(
                AccountSuspendedEvent(
                    account_id=account_id,
                    reason="Account deletion",
                    suspended_by=deleted_by,
                )
            )

        account.status = AccountStatus.DELETED
        account.updated_at = datetime.now(UTC)

        await self._db.execute(
            "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
            (AccountStatus.DELETED, account.updated_at.isoformat(), account_id),
        )

        # 메모리 캐시에서 제거
        self._accounts.pop(account_id, None)
        # 브로커 캐시에서도 제거
        self._brokers.pop(account_id, None)

        logger.info("계좌 삭제: %s (요청자: %s)", account_id, deleted_by)

    async def _count_active_bots(self, account_id: str) -> int:
        """``bots`` 테이블에서 동일 account_id의 non-deleted 봇 수를 센다.

        ``bots`` 테이블이 존재하지 않는 환경(BotManager 미초기화 단위 테스트
        등)은 0을 반환한다. 운영 서버는 항상 BotManager 초기화 시점에
        스키마를 적용하므로 이 fallback은 cold-path CLI 실행 환경 차이만
        흡수한다.
        """
        try:
            row = await self._db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM bots WHERE account_id = ? AND status != ?",
                (account_id, "deleted"),
            )
        except Exception:
            # bots 테이블 부재 등 → active 봇 없음으로 간주
            return 0

        if row is None:
            return 0
        cnt = row.get("cnt", 0) if isinstance(row, dict) else row[0]
        return int(cnt or 0)

    # ── 일괄 상태 전이 ──────────────────────────────────

    async def suspend_all(self, reason: str, suspended_by: str) -> _AccountStatusReport:
        """모든 ACTIVE 계좌를 SUSPENDED로 전환. DELETED 계좌는 후보 제외.

        Returns:
            처리 대상 계좌(ACTIVE/SUSPENDED)별 변경 결과 목록. DELETED 계좌는
            포함되지 않는다. 각 항목은 다음 키를 가진다:

            - ``account_id`` (str)
            - ``previous_status`` (str): 호출 직전 상태 (소문자 wire 값)
            - ``status`` (str): 호출 직후 상태 (소문자 wire 값)
            - ``changed`` (bool): 실제 전환 여부

        SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답.
        """
        results: list[dict[str, Any]] = []
        for account_id in list(self._accounts.keys()):
            account = self._accounts[account_id]
            if account.status == AccountStatus.DELETED:
                continue
            previous_status = account.status.value
            if account.status == AccountStatus.ACTIVE:
                await self.suspend(account_id, reason, suspended_by)
                changed = True
            else:
                changed = False
            results.append(
                {
                    "account_id": account_id,
                    "previous_status": previous_status,
                    "status": AccountStatus.SUSPENDED.value,
                    "changed": changed,
                }
            )
        changed_count = sum(1 for r in results if r["changed"])
        logger.info("전체 계좌 정지: %d개 (사유: %s)", changed_count, reason)
        return results

    async def activate_all(self, activated_by: str) -> _AccountStatusReport:
        """모든 SUSPENDED 계좌를 ACTIVE로 복구. DELETED 계좌는 후보 제외.

        Returns:
            처리 대상 계좌(ACTIVE/SUSPENDED)별 변경 결과 목록. DELETED 계좌는
            포함되지 않는다. 각 항목은 다음 키를 가진다:

            - ``account_id`` (str)
            - ``previous_status`` (str): 호출 직전 상태 (소문자 wire 값)
            - ``status`` (str): 호출 직후 상태 (소문자 wire 값)
            - ``changed`` (bool): 실제 전환 여부

        계좌 상태만 ACTIVE로 복구하며 봇 자동 재시작은 수행하지 않는다
        (BotManager는 ``AccountActivatedEvent`` 수신 시 로깅만 수행).

        SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답.
        """
        results: list[dict[str, Any]] = []
        for account_id in list(self._accounts.keys()):
            account = self._accounts[account_id]
            if account.status == AccountStatus.DELETED:
                continue
            previous_status = account.status.value
            if account.status == AccountStatus.SUSPENDED:
                await self.activate(account_id, activated_by)
                changed = True
            else:
                changed = False
            results.append(
                {
                    "account_id": account_id,
                    "previous_status": previous_status,
                    "status": AccountStatus.ACTIVE.value,
                    "changed": changed,
                }
            )
        changed_count = sum(1 for r in results if r["changed"])
        logger.info("전체 계좌 활성화: %d개", changed_count)
        return results

    # ── 브로커 인스턴스 ──────────────────────────────────

    async def get_broker(self, account_id: str) -> BrokerAdapter:
        """계좌의 BrokerAdapter 인스턴스를 반환. lazy init + 캐싱.

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            InvalidBrokerTypeError: broker_type이 BROKER_REGISTRY에 등록되지 않음.
        """
        if account_id in self._brokers:
            return self._brokers[account_id]

        broker = await self._build_broker_adapter(account_id)
        self._brokers[account_id] = broker
        return broker

    async def _build_broker_adapter(self, account_id: str) -> BrokerAdapter:
        """현재 DB 상태로 BrokerAdapter를 생성한다 (캐시하지 않음).

        `get_broker()`의 최초 생성 경로와 `_reconnect_broker()`의 재생성
        경로가 공유한다. 캐시 쓰기는 호출자가 책임진다 — 특히 재연결은
        connect() 성공을 확인한 뒤에 캐시를 교체한다.
        """
        _register_brokers()

        account = await self.get(account_id)
        broker_cls = _BROKER_REGISTRY.get(account.broker_type)
        if broker_cls is None:
            raise InvalidBrokerTypeError(
                f"broker_type '{account.broker_type}'은 BROKER_REGISTRY에 "
                f"등록되지 않았습니다. 등록된 타입: {list(_BROKER_REGISTRY.keys())}"
            )

        config: dict[str, Any] = {
            "exchange": account.exchange,
            "trading_mode": account.trading_mode.value,
            "buy_commission_rate": float(account.buy_commission_rate),
            "sell_commission_rate": float(account.sell_commission_rate),
            **account.credentials,
            **account.broker_config,
        }

        broker = broker_cls(config)
        logger.info(
            "브로커 인스턴스 생성: %s (type=%s)",
            account_id,
            account.broker_type,
        )
        return broker

    # ── 기본 테스트 계좌 ──────────────────────────────────

    async def create_default_test_account(self) -> Account:
        """테스트 계좌 자동 생성. 이미 존재하면 기존 계좌 반환.

        bootstrap seed 경로이므로 ``validate_new_account_id`` 의 RESTRICTED
        거부( ``"test"`` )가 적용되지 않는 private helper
        :meth:`_create_seed_account` 를 통해 생성한다.
        ``BROKER_PRESETS["test"].default_account_id`` 가 ``account_id`` SSOT 이며,
        이 메서드가 seed helper를 호출하는 유일한 진입점이다 (#1216 P2).
        """
        if "test" in self._accounts:
            return self._accounts["test"]

        preset = BROKER_PRESETS["test"]
        account = Account(
            account_id=preset.default_account_id,
            name=preset.default_name,
            exchange=preset.exchange,
            currency=preset.currency,
            timezone=preset.timezone,
            trading_hours_start=preset.trading_hours_start,
            trading_hours_end=preset.trading_hours_end,
            trading_mode=TradingMode.VIRTUAL,
            broker_type="test",
            credentials={k: "test" for k in preset.required_credentials},
            buy_commission_rate=preset.buy_commission_rate,
            sell_commission_rate=preset.sell_commission_rate,
        )
        return await self._create_seed_account(account)


# ── 유틸리티 ──────────────────────────────────────────


def _row_to_account(row: dict[str, Any]) -> Account:
    """DB 행을 Account 객체로 변환."""
    credentials_raw = row.get("credentials", "{}")
    if isinstance(credentials_raw, str):
        credentials = decrypt_credentials(credentials_raw)
    else:
        credentials = credentials_raw

    broker_config_raw = row.get("broker_config", "{}")
    broker_config: dict[str, Any] = (
        json.loads(broker_config_raw)
        if isinstance(broker_config_raw, str)
        else (broker_config_raw or {})
    )

    return Account(
        account_id=row["account_id"],
        name=row["name"],
        exchange=row["exchange"],
        currency=row["currency"],
        timezone=row["timezone"],
        trading_hours_start=row["trading_hours_start"],
        trading_hours_end=row["trading_hours_end"],
        trading_mode=TradingMode(row["trading_mode"]),
        broker_type=row["broker_type"],
        credentials=credentials,
        broker_config=broker_config,
        buy_commission_rate=Decimal(str(row["buy_commission_rate"])),
        sell_commission_rate=Decimal(str(row["sell_commission_rate"])),
        status=AccountStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"])
        if row.get("created_at")
        else None,
        updated_at=datetime.fromisoformat(row["updated_at"])
        if row.get("updated_at")
        else None,
    )
