"""AccountService — 계좌 CRUD 및 상태 관리."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ante.account.crypto import decrypt_credentials, encrypt_credentials
from ante.account.errors import (
    AccountActivateAllFailedError,
    AccountAlreadyExistsError,
    AccountDeletedException,
    AccountHasActiveBotsError,
    AccountImmutableFieldError,
    AccountNotFoundError,
    AccountReconcileNotApplicableError,
    AccountStructuralChangeRequiresStoppedServerError,
    AccountSuspendAllFailedError,
    AccountSuspendNotPersistedError,
    BrokerReconnectFailedError,
    InvalidAccountIdError,
    InvalidBrokerConfigError,
    InvalidBrokerTypeError,
    InvalidExchangeError,
    MissingCredentialsError,
)
from ante.account.models import (
    ACCOUNT_STATUS_TRANSITIONS,
    Account,
    AccountStatus,
    TradingMode,
    missing_required_credentials,
)
from ante.account.presets import BROKER_PRESETS, VIRTUAL_ONLY_BROKER_TYPES
from ante.account.readiness import ReadinessFlag, is_flag_exempt
from ante.account.scoping import require_account_id, validate_new_account_id
from ante.account.timezone import validate_iana_timezone
from ante.core import clock
from ante.core.database import OperationalError, is_missing_table
from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical
from ante.core.price import is_valid_price

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

_BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {}

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
    market_order_reserve_buffer_rate REAL NOT NULL DEFAULT 0.005,
    status       TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'suspended', 'deleted')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_ACCOUNTS_BUFFER_MIGRATION = (
    "ALTER TABLE accounts "
    "ADD COLUMN market_order_reserve_buffer_rate REAL NOT NULL DEFAULT 0.005;"
)
_ACCOUNTS_BUFFER_BACKFILL_TEST = (
    "UPDATE accounts SET market_order_reserve_buffer_rate = 0 "
    "WHERE broker_type = 'test';"
)


def _register_brokers() -> None:
    """브로커 어댑터를 lazy 등록한다."""
    if _BROKER_REGISTRY:
        return

    from ante.broker.kis import KISAdapter
    from ante.broker.mock import MockBrokerAdapter
    from ante.broker.test import TestBrokerAdapter

    _BROKER_REGISTRY["test"] = TestBrokerAdapter
    _BROKER_REGISTRY["kis-domestic"] = KISAdapter
    _BROKER_REGISTRY["mock"] = MockBrokerAdapter


def _reject_virtual_only_broker_in_live(account: Account) -> None:
    if (
        account.broker_type in VIRTUAL_ONLY_BROKER_TYPES
        and account.trading_mode != TradingMode.VIRTUAL
    ):
        raise InvalidBrokerTypeError(
            f"broker_type '{account.broker_type}'은 가상 전용이라 "
            f"trading_mode '{account.trading_mode.value}'와 함께 쓸 수 없습니다. "
            "trading_mode 'virtual'로 만드세요."
        )


def _reject_invalid_mock_prices(account: Account) -> None:
    """``mock`` 계좌의 ``broker_config`` 가격 값을 가격 정의로 검사한다."""
    if account.broker_type != "mock":
        return
    config = account.broker_config
    if "prices" in config:
        prices = config["prices"]
        if not isinstance(prices, dict):
            raise InvalidBrokerConfigError(
                f"mock 계좌의 broker_config prices는 객체여야 합니다: {prices!r}"
            )
        invalid = {
            symbol: value
            for symbol, value in prices.items()
            if not is_valid_price(value)
        }
        if invalid:
            raise InvalidBrokerConfigError(
                "mock 계좌의 broker_config prices 값은 불리언이 아닌 "
                f"0보다 큰 유한한 수여야 합니다: {invalid!r}"
            )
    if "default_price" in config and not is_valid_price(config["default_price"]):
        raise InvalidBrokerConfigError(
            "mock 계좌의 broker_config default_price는 불리언이 아닌 "
            f"0보다 큰 유한한 수여야 합니다: {config['default_price']!r}"
        )


def _transition_status(account: Account, target: AccountStatus) -> AccountStatus:
    if target not in ACCOUNT_STATUS_TRANSITIONS.get(account.status, set()):
        raise ValueError(
            f"계좌 '{account.account_id}' 상태 '{account.status}' 에서 "
            f"'{target}' 으로 전이할 수 없습니다."
        )
    account.status = target
    return target


def _restore_status(
    account: Account, status: AccountStatus, updated_at: datetime | None
) -> None:
    """상태 쓰기가 실패한 캐시 계좌를 호출 전 상태로 되돌린다."""
    account.status = status
    account.updated_at = updated_at


STRUCTURAL_FIELDS: frozenset[str] = frozenset(
    {
        "credentials",
        "broker_config",
        "buy_commission_rate",
        "sell_commission_rate",
        "market_order_reserve_buffer_rate",
        "broker_type",
        "exchange",
        "currency",
        "trading_mode",
    }
)


def _load_persisted_timezone(stored_tz: str, account_id: str) -> tuple[str, bool]:
    """저장된 timezone 값을 tolerant load 하고 ``timezone_invalid`` marker 반환."""
    try:
        validate_iana_timezone(stored_tz)
    except ValueError as e:
        logger.warning(
            "ACCOUNT_INVALID_TIMEZONE_LEGACY: invalid timezone in stored "
            "account row (legacy migration 필요): account_id=%s stored=%r — %s. "
            "Repair: `ante account repair-timezone %s <new_iana_timezone>` "
            "(cold-path).",
            account_id,
            stored_tz,
            e,
            account_id,
        )
        return stored_tz, True
    return stored_tz, False


def _reject_missing_credentials(broker_type: str, credentials: dict[str, Any]) -> None:
    """프리셋의 필수 인증정보가 비어 있으면 키 이름만 실어 거부한다."""
    preset = BROKER_PRESETS[broker_type]
    missing = missing_required_credentials(preset.required_credentials, credentials)
    if missing:
        raise MissingCredentialsError(
            f"필수 credentials 누락: {missing}. "
            f"broker_type '{broker_type}'에 필요: "
            f"{preset.required_credentials}"
        )


class AccountService:
    """계좌 CRUD, 상태 관리, 브로커 인스턴스 생성."""

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus
        self._accounts: dict[str, Account] = {}
        self._brokers: dict[str, BrokerAdapter] = {}
        self._broker_locks: dict[str, asyncio.Lock] = {}
        self._runtime_started: bool = False
        self._unpersisted_suspensions: set[str] = set()

    def mark_runtime_started(self) -> None:
        """서버 부팅 mutation을 모두 마쳤음을 표시한다 (invariant S1/S3).

        이 호출 이후로 ``create()``, ``delete()``, structural 키를 포함한
        ``update()`` 호출은 ``AccountStructuralChangeRequiresStoppedServerError``로
        즉시 차단된다 — DB는 수정되지 않는다.

        멱등: 이미 True 상태에서 호출하면 no-op.
        """
        self._runtime_started = True

    def has_unpersisted_suspensions(self) -> bool:
        """이 실행에서 DB에 기록되지 않은 계좌 정지가 남아 있는지 돌려준다."""
        return bool(self._unpersisted_suspensions)

    async def initialize(self) -> None:
        """스키마 생성 + DB에서 계좌 목록 로드."""
        await self._db.execute_script(_CREATE_TABLE_SQL)
        migrated = False
        try:
            await self._db.execute_script(_ACCOUNTS_BUFFER_MIGRATION)
            migrated = True
        except Exception:
            pass
        if migrated:
            try:
                await self._db.execute(_ACCOUNTS_BUFFER_BACKFILL_TEST)
            except Exception:
                logger.debug(
                    "market_order_reserve_buffer_rate backfill 무시.",
                    exc_info=True,
                )
        rows = await self._db.fetch_all(
            "SELECT * FROM accounts WHERE status != ?",
            (AccountStatus.DELETED,),
        )
        invalid_timezone_account_ids: list[str] = []
        for row in rows:
            account = _row_to_account(row)
            if account.timezone_invalid:
                invalid_timezone_account_ids.append(account.account_id)
            self._accounts[account.account_id] = account
        logger.info("AccountService 초기화 완료: %d개 계좌 로드", len(self._accounts))
        if invalid_timezone_account_ids:
            logger.warning(
                "ACCOUNT_INVALID_TIMEZONE_LEGACY summary: count=%d, account_ids=%s",
                len(invalid_timezone_account_ids),
                sorted(invalid_timezone_account_ids),
            )

    async def create(self, account: Account) -> Account:
        """계좌 생성. **cold-path 전용**.

        Returns:
            생성된 Account (created_at, updated_at 포함).

        Raises:
            AccountStructuralChangeRequiresStoppedServerError: 서버 실행 중
                호출됨. 다른 어떤 검사보다 먼저 평가된다 (invariant S2).
        """
        self._guard_cold_path_create()

        validate_new_account_id(account.account_id)

        if account.timezone:
            validate_iana_timezone(account.timezone)

        return await self._persist_account(account)

    async def _create_seed_account(self, account: Account) -> Account:
        """Bootstrap seed 계좌 생성 (**private**)."""
        self._guard_cold_path_create()

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
        require_account_id(account.account_id, context="bootstrap_seed")

        if account.timezone:
            validate_iana_timezone(account.timezone)

        return await self._persist_account(account)

    def _guard_cold_path_create(self) -> None:
        """``create*()`` 진입 시 런타임 cold-path 가드 (invariant S2)."""
        if self._runtime_started:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "계좌 생성은 cold-path 전용입니다. "
                "서버를 정지한 뒤 ante account create로 수행하세요."
            )

    async def _persist_account(self, account: Account) -> Account:
        """``account_id`` 검증 이후 공통 검증 + DB insert (private helper)."""
        if account.account_id in self._accounts:
            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다."
            )

        deleted = await self._db.fetch_one(
            "SELECT account_id FROM accounts WHERE account_id = ? AND status = ?",
            (account.account_id, AccountStatus.DELETED),
        )
        if deleted:
            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다 (삭제 상태)."
            )

        if not is_canonical(account.exchange):
            raise InvalidExchangeError(
                f"유효하지 않은 exchange: '{account.exchange}'. "
                f"가능한 값: {sorted(CANONICAL_EXCHANGES)}"
            )

        if account.broker_type not in BROKER_PRESETS:
            raise InvalidBrokerTypeError(
                f"유효하지 않은 broker_type: '{account.broker_type}'. "
                f"가능한 값: {list(BROKER_PRESETS.keys())}"
            )
        _reject_virtual_only_broker_in_live(account)
        _reject_invalid_mock_prices(account)

        _reject_missing_credentials(account.broker_type, account.credentials)

        now = clock.now(UTC)
        account.created_at = now
        account.updated_at = now

        await self._db.execute(
            """INSERT INTO accounts
               (account_id, name, exchange, currency, timezone,
                trading_hours_start, trading_hours_end, trading_mode,
                broker_type, credentials, broker_config,
                buy_commission_rate, sell_commission_rate,
                market_order_reserve_buffer_rate,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                float(account.market_order_reserve_buffer_rate),
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
        if account_id in self._accounts:
            return self._accounts[account_id]

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
                rows = await self._db.fetch_all(
                    "SELECT * FROM accounts WHERE status = ?",
                    (AccountStatus.DELETED,),
                )
                return [_row_to_account(row) for row in rows]
            return [a for a in self._accounts.values() if a.status == status]
        return list(self._accounts.values())

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
        우선이다 (invariant S2).
        """
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
            "market_order_reserve_buffer_rate",
        }
        unrecognized = set(fields.keys()) - updatable - self.IMMUTABLE_FIELDS
        if unrecognized:
            raise ValueError(f"인식할 수 없는 필드입니다: {sorted(unrecognized)}")

        if "credentials" in fields and account.broker_type in BROKER_PRESETS:
            _reject_missing_credentials(
                account.broker_type, fields["credentials"] or {}
            )

        timezone_update = fields.get("timezone")
        if timezone_update is not None:
            validate_iana_timezone(timezone_update)
        broker_invalidating = {
            "credentials",
            "broker_config",
            "buy_commission_rate",
            "sell_commission_rate",
        }
        invalidate_broker = bool(set(fields.keys()) & broker_invalidating)
        timezone_explicit_update = "timezone" in fields and timezone_update is not None
        for key, value in fields.items():
            if key not in updatable:
                continue
            setattr(account, key, value)
        if timezone_explicit_update:
            account.timezone_invalid = False

        now = clock.now(UTC)
        account.updated_at = now

        await self._db.execute(
            """UPDATE accounts SET
               name=?, exchange=?, currency=?, timezone=?,
               trading_hours_start=?, trading_hours_end=?, trading_mode=?,
               broker_type=?, credentials=?, broker_config=?,
               buy_commission_rate=?, sell_commission_rate=?,
               market_order_reserve_buffer_rate=?,
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
                float(account.market_order_reserve_buffer_rate),
                now.isoformat(),
                account_id,
            ),
        )

        self._accounts[account_id] = account
        if invalidate_broker:
            await self._reconnect_broker(account_id)
        logger.info("계좌 수정: %s", account_id)
        return account

    async def repair_timezone(self, account_id: str, new_timezone: str) -> Account:
        """legacy invalid IANA timezone row 를 valid 값으로 복구 (**cold-path**).

        cold-path 의미론: 서버 runtime 중에는
        ``AccountStructuralChangeRequiresStoppedServerError`` 로 즉시
        차단된다. ``update()`` 자체는 timezone 을 updatable field 로
        허용하므로 cold-path 보장이 본 메서드 책임이다. ingress 검증과
        DB/캐시 UPDATE 는 ``update(timezone=...)`` 에 위임하여 single
        SSOT 를 유지한다 (별도 DB UPDATE 중복 금지).
        """
        if self._runtime_started:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "account.repair_timezone is a cold-path operation; "
                "stop the server before invoking this command."
            )
        return await self.update(account_id, timezone=new_timezone)

    async def _reconnect_broker(self, account_id: str) -> None:
        """새 브로커 어댑터를 생성·연결한 뒤에만 캐시를 교체한다."""
        async with self._broker_lock_for(account_id):
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

            self._brokers[account_id] = new_broker

    async def suspend(self, account_id: str, reason: str, suspended_by: str) -> None:
        """계좌 정지 (status -> SUSPENDED). 미기록 정지면 상태 쓰기만 다시 한다.

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: 삭제된 계좌.
            AccountSuspendNotPersistedError: 정지는 적용됐지만 DB 쓰기가 실패함.
        """
        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(
                f"삭제된 계좌 '{account_id}'는 정지할 수 없습니다."
            )
        if (
            account.status == AccountStatus.SUSPENDED
            and account_id not in self._unpersisted_suspensions
        ):
            from ante.account.errors import AccountAlreadySuspendedError

            raise AccountAlreadySuspendedError(
                f"이미 정지된 계좌입니다: '{account_id}'"
            )
        if account.status == AccountStatus.ACTIVE:
            status = _transition_status(account, AccountStatus.SUSPENDED)
        else:
            status = AccountStatus.SUSPENDED
        account.updated_at = clock.now(UTC)

        from ante.eventbus.events import AccountSuspendedEvent, NotificationEvent

        try:
            await self._db.execute(
                "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
                (status, account.updated_at.isoformat(), account_id),
            )
        except Exception as exc:
            self._unpersisted_suspensions.add(account_id)
            logger.error(
                "계좌 정지 DB 기록 실패 (메모리 정지 유지): %s",
                account_id,
                exc_info=True,
            )
            await self._eventbus.publish(
                AccountSuspendedEvent(
                    account_id=account_id,
                    reason=reason,
                    suspended_by=suspended_by,
                )
            )
            await self._eventbus.publish(
                NotificationEvent(
                    level="critical",
                    title="계좌 정지 기록 실패 (킬 스위치)",
                    message=(
                        f"계좌 `{account_id}` 정지(SUSPENDED)는 적용됐지만 "
                        "DB에 기록되지 않았습니다.\n"
                        "재시작하면 활성으로 돌아옵니다. 정지를 다시 보내 기록하세요.\n"
                        f"사유: {reason}\n"
                        f"실행: `{suspended_by}`"
                    ),
                    category="system",
                )
            )
            raise AccountSuspendNotPersistedError(
                f"계좌 '{account_id}'의 정지는 적용됐지만 DB에 기록되지 않았습니다. "
                "재시작하면 활성으로 돌아옵니다. 정지를 다시 보내면 기록을 다시 "
                "시도합니다."
            ) from exc
        except BaseException:
            self._unpersisted_suspensions.add(account_id)
            raise
        self._unpersisted_suspensions.discard(account_id)

        await self._eventbus.publish(
            AccountSuspendedEvent(
                account_id=account_id,
                reason=reason,
                suspended_by=suspended_by,
            )
        )
        await self._eventbus.publish(
            NotificationEvent(
                level="critical",
                title="거래 상태 변경 (킬 스위치)",
                message=(
                    f"계좌 `{account_id}` 정지(SUSPENDED)\n"
                    f"사유: {reason}\n"
                    f"실행: `{suspended_by}`"
                ),
                category="system",
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

        previous_status, previous_updated_at = account.status, account.updated_at
        status = _transition_status(account, AccountStatus.ACTIVE)
        account.updated_at = clock.now(UTC)

        try:
            await self._db.execute(
                "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
                (status, account.updated_at.isoformat(), account_id),
            )
        except BaseException:
            _restore_status(account, previous_status, previous_updated_at)
            raise
        self._unpersisted_suspensions.discard(account_id)

        from ante.eventbus.events import AccountActivatedEvent, NotificationEvent

        await self._eventbus.publish(
            AccountActivatedEvent(
                account_id=account_id,
                activated_by=activated_by,
            )
        )
        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="거래 상태 변경 (킬 스위치 해제)",
                message=(f"계좌 `{account_id}` 재활성(ACTIVE)\n실행: `{activated_by}`"),
                category="system",
            )
        )

        logger.info("계좌 활성화: %s (요청자: %s)", account_id, activated_by)

    async def delete(self, account_id: str, deleted_by: str) -> None:
        """소프트 딜리트 (status -> DELETED). cold-path 전용."""
        if self._runtime_started:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "계좌 삭제는 cold-path 전용입니다. "
                "서버를 정지한 뒤 ante account delete로 수행하세요."
            )

        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(f"이미 삭제된 계좌입니다: '{account_id}'")

        active_bot_count = await self._count_active_bots(account_id)
        if active_bot_count > 0:
            raise AccountHasActiveBotsError(
                account_id=account_id, bot_count=active_bot_count
            )

        previous_status, previous_updated_at = account.status, account.updated_at
        status = _transition_status(account, AccountStatus.DELETED)
        account.updated_at = clock.now(UTC)

        try:
            await self._db.execute(
                "UPDATE accounts SET status=?, updated_at=? WHERE account_id=?",
                (status, account.updated_at.isoformat(), account_id),
            )
        except BaseException:
            _restore_status(account, previous_status, previous_updated_at)
            raise
        self._unpersisted_suspensions.discard(account_id)

        self._accounts.pop(account_id, None)
        self._brokers.pop(account_id, None)

        if previous_status not in (AccountStatus.SUSPENDED, AccountStatus.DELETED):
            from ante.eventbus.events import AccountSuspendedEvent

            await self._eventbus.publish(
                AccountSuspendedEvent(
                    account_id=account_id,
                    reason="Account deletion",
                    suspended_by=deleted_by,
                )
            )

        logger.info("계좌 삭제: %s (요청자: %s)", account_id, deleted_by)

    async def _count_active_bots(self, account_id: str) -> int:
        """``bots`` 테이블에서 동일 account_id의 non-deleted 봇 수를 센다."""
        try:
            row = await self._db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM bots WHERE account_id = ? AND status != ?",
                (account_id, "deleted"),
            )
        except OperationalError as exc:
            if is_missing_table(exc):
                return 0
            raise

        if row is None:
            return 0
        cnt = row.get("cnt", 0) if isinstance(row, dict) else row[0]
        return int(cnt or 0)

    async def suspend_all(self, reason: str, suspended_by: str) -> _AccountStatusReport:
        """모든 ACTIVE 계좌를 SUSPENDED로 전환. DELETED 계좌는 후보 제외.

        Returns:
            처리 대상 계좌(ACTIVE/SUSPENDED)별 변경 결과 목록. DELETED 계좌는
            포함되지 않는다. 각 항목은 다음 키를 가진다:
            - ``account_id`` (str)
            - ``previous_status`` (str): 호출 직전 상태 (소문자 wire 값)
            - ``status`` (str): 호출 직후 상태 (소문자 wire 값)
            - ``changed`` (bool): 실제 전환 여부
        """
        candidates = [
            (account_id, account, account.status)
            for account_id, account in list(self._accounts.items())
            if account.status != AccountStatus.DELETED
        ]
        for account_id, account, previous in candidates:
            if previous == AccountStatus.ACTIVE:
                _transition_status(account, AccountStatus.SUSPENDED)
                self._unpersisted_suspensions.add(account_id)
        results: list[dict[str, Any]] = []
        failed: list[str] = []
        for account_id, account, previous in candidates:
            if (
                account.status == AccountStatus.ACTIVE
                or account_id in self._unpersisted_suspensions
            ):
                try:
                    await self.suspend(account_id, reason, suspended_by)
                except Exception:
                    logger.exception("전체 계좌 정지 중 계좌 정지 실패: %s", account_id)
                    failed.append(account_id)
                    continue
            results.append(
                {
                    "account_id": account_id,
                    "previous_status": previous.value,
                    "status": AccountStatus.SUSPENDED.value,
                    "changed": previous == AccountStatus.ACTIVE,
                }
            )
        changed_count = sum(1 for r in results if r["changed"])
        if failed:
            logger.error(
                "전체 계좌 정지 일부 실패: 실패 %d개, 정지 %d개 (사유: %s)",
                len(failed),
                changed_count,
                reason,
            )
            raise AccountSuspendAllFailedError(
                failed_account_ids=tuple(failed), suspended_count=changed_count
            )
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
        """
        results: list[dict[str, Any]] = []
        for account_id in list(self._accounts.keys()):
            account = self._accounts[account_id]
            if account.status == AccountStatus.DELETED:
                continue
            previous_status = account.status.value
            if account.status == AccountStatus.SUSPENDED:
                try:
                    await self.activate(account_id, activated_by)
                except Exception as exc:
                    logger.exception(
                        "전체 계좌 활성화 중 계좌 활성화 실패: %s", account_id
                    )
                    raise AccountActivateAllFailedError(
                        failed_account_id=account_id,
                        activated_count=sum(1 for r in results if r["changed"]),
                    ) from exc
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

    def _broker_lock_for(self, account_id: str) -> asyncio.Lock:
        """계좌별 브로커 직렬화 lock 을 반환한다 (없으면 생성)."""
        return self._broker_locks.setdefault(account_id, asyncio.Lock())

    async def get_broker(self, account_id: str) -> BrokerAdapter:
        """계좌의 BrokerAdapter 인스턴스를 반환. lazy init + 연결-성공-후-캐싱.

        최초 호출 시 어댑터를 생성하고 ``connect()`` 를 수행하며, **연결에
        성공한 경우에만** 캐시에 기록한 뒤 반환한다. connect 가 실패하면
        캐시에 남기지 않고 예외를 전파하므로, 일시적 인증/네트워크
        오류로 미연결 adapter 가 캐시에 잔존해 후속 소비자가 재사용하는 일이
        없다. 이는 재연결 경로(:meth:`_reconnect_broker`)의 connect-성공-후-캐시
        원칙과 동일하다 — 초기 경로의 비대칭을 제거한다.
        """
        broker = self._brokers.get(account_id)
        if broker is not None:
            return broker

        async with self._broker_lock_for(account_id):
            broker = self._brokers.get(account_id)
            if broker is not None:
                return broker

            broker = await self._build_broker_adapter(account_id)
            await broker.connect()
            self._brokers[account_id] = broker
            return broker

    async def ensure_reconcile_applicable(self, account_id: str) -> None:
        """수동 대사를 할 수 있는 계좌인지 판정한다. 브로커는 만들지 않는다.

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountReconcileNotApplicableError: D-ACC-09 매트릭스에서 reconcile
                이 면제인 계좌(가상).
        """
        account = await self.get(account_id)
        if is_flag_exempt(
            ReadinessFlag.RECONCILE,
            broker_type=account.broker_type,
            trading_mode=account.trading_mode,
        ):
            raise AccountReconcileNotApplicableError(
                f"계좌 '{account_id}'는 가상 계좌라 브로커와 대사하지 않습니다. "
                "가상 계좌의 포지션은 내부 기록이 기준입니다."
            )

    async def get_cached_broker(self, account_id: str) -> BrokerAdapter | None:
        """이미 캐시된 BrokerAdapter 만 반환한다 (build/connect 없음).

        캐시에 없으면 ``None`` 을 반환하며 새 어댑터를 생성하거나 연결하지
        않는다. 종료(shutdown) 루프처럼 "이미 연결된 어댑터만 끊으면 되는"
        경로에서 사용한다 — 미캐시 계좌를 끊기 위해 새로 인증/연결하는 회귀를
        차단한다(미캐시 = 끊을 연결도 없음).

        새 adapter 생성/connect 는 일으키지 않는다(lock 안에서 단순 조회).
        lock 보유 중 본 메서드를 호출하는 경로가 없어 재귀 deadlock 도 없다.
        """
        async with self._broker_lock_for(account_id):
            return self._brokers.get(account_id)

    async def _build_broker_adapter(self, account_id: str) -> BrokerAdapter:
        """현재 DB 상태로 BrokerAdapter를 생성한다 (캐시하지 않음)."""
        _register_brokers()

        account = await self.get(account_id)
        _reject_virtual_only_broker_in_live(account)
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

    async def create_default_test_account(self) -> Account:
        """테스트 계좌 자동 생성. 이미 존재하면 기존 계좌 반환.

        bootstrap seed 경로이므로 ``validate_new_account_id`` 의 RESTRICTED
        거부( ``"test"`` )가 적용되지 않는 private helper
        :meth:`_create_seed_account` 를 통해 생성한다.
        ``BROKER_PRESETS["test"].default_account_id`` 가 ``account_id`` SSOT 이며,
        이 메서드가 seed helper를 호출하는 유일한 진입점이다.
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
            market_order_reserve_buffer_rate=preset.market_order_reserve_buffer_rate,
        )
        return await self._create_seed_account(account)


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

    buffer_raw = row.get("market_order_reserve_buffer_rate")
    buffer_value = (
        (Decimal("0") if row["broker_type"] == "test" else Decimal("0.005"))
        if buffer_raw is None
        else Decimal(str(buffer_raw))
    )

    tz_value, tz_invalid = _load_persisted_timezone(row["timezone"], row["account_id"])

    return Account(
        account_id=row["account_id"],
        name=row["name"],
        exchange=row["exchange"],
        currency=row["currency"],
        timezone=tz_value,
        timezone_invalid=tz_invalid,
        trading_hours_start=row["trading_hours_start"],
        trading_hours_end=row["trading_hours_end"],
        trading_mode=TradingMode(row["trading_mode"]),
        broker_type=row["broker_type"],
        credentials=credentials,
        broker_config=broker_config,
        buy_commission_rate=Decimal(str(row["buy_commission_rate"])),
        sell_commission_rate=Decimal(str(row["sell_commission_rate"])),
        market_order_reserve_buffer_rate=buffer_value,
        status=AccountStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"])
        if row.get("created_at")
        else None,
        updated_at=datetime.fromisoformat(row["updated_at"])
        if row.get("updated_at")
        else None,
    )
