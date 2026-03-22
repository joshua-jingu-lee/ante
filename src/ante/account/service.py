"""AccountService — 계좌 CRUD 및 상태 관리."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ante.account.crypto import decrypt_credentials, encrypt_credentials
from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountDeletedException,
    AccountImmutableFieldError,
    AccountNotFoundError,
    InvalidBrokerTypeError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.presets import BROKER_PRESETS

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# 브로커 어댑터 레지스트리 — broker_type → 어댑터 클래스
# kis-overseas는 1.1에서 등록 예정
_BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {}

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


class AccountService:
    """계좌 CRUD, 상태 관리, 브로커 인스턴스 생성."""

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus
        self._accounts: dict[str, Account] = {}
        self._brokers: dict[str, BrokerAdapter] = {}

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
        """계좌 생성.

        Args:
            account: 생성할 계좌 정보.

        Returns:
            생성된 Account (created_at, updated_at 포함).

        Raises:
            AccountAlreadyExistsError: 동일 account_id가 이미 존재.
            InvalidBrokerTypeError: broker_type이 프리셋에 정의되지 않음.
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

        now = datetime.now(UTC)
        account.created_at = now
        account.updated_at = now

        await self._db.execute(
            """INSERT INTO accounts
               (account_id, name, exchange, currency, timezone,
                trading_hours_start, trading_hours_end, trading_mode,
                broker_type, credentials, buy_commission_rate, sell_commission_rate,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: DELETED 계좌는 수정 불가.
            AccountImmutableFieldError: 불변 필드 수정 시도.
        """
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
            "buy_commission_rate",
            "sell_commission_rate",
        }
        unrecognized = set(fields.keys()) - updatable - self.IMMUTABLE_FIELDS
        if unrecognized:
            raise ValueError(f"인식할 수 없는 필드입니다: {sorted(unrecognized)}")
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
               broker_type=?, credentials=?,
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
                float(account.buy_commission_rate),
                float(account.sell_commission_rate),
                now.isoformat(),
                account_id,
            ),
        )

        self._accounts[account_id] = account
        logger.info("계좌 수정: %s", account_id)
        return account

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
        """소프트 딜리트 (status -> DELETED).

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            AccountDeletedException: 삭제된 계좌.
        """
        account = await self.get(account_id)
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedException(f"이미 삭제된 계좌입니다: '{account_id}'")

        # 소속 봇 중지 트리거 (이미 SUSPENDED/DELETED면 스킵)
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

        # 삭제 완료 이벤트
        from ante.eventbus.events import AccountDeletedEvent

        await self._eventbus.publish(
            AccountDeletedEvent(account_id=account_id, deleted_by=deleted_by)
        )

        # 메모리 캐시에서 제거
        self._accounts.pop(account_id, None)
        # 브로커 캐시에서도 제거
        self._brokers.pop(account_id, None)

        logger.info("계좌 삭제: %s (요청자: %s)", account_id, deleted_by)

    # ── 일괄 상태 전이 ──────────────────────────────────

    async def suspend_all(self, reason: str, suspended_by: str) -> int:
        """모든 ACTIVE 계좌를 SUSPENDED로 전환. DELETED 제외.

        Returns:
            전환된 계좌 수.
        """
        count = 0
        for account_id in list(self._accounts.keys()):
            account = self._accounts[account_id]
            if account.status == AccountStatus.ACTIVE:
                await self.suspend(account_id, reason, suspended_by)
                count += 1
        logger.info("전체 계좌 정지: %d개 (사유: %s)", count, reason)
        return count

    async def activate_all(self, activated_by: str) -> int:
        """모든 SUSPENDED 계좌를 ACTIVE로 복구. DELETED 제외.

        Returns:
            전환된 계좌 수.
        """
        count = 0
        for account_id in list(self._accounts.keys()):
            account = self._accounts[account_id]
            if account.status == AccountStatus.SUSPENDED:
                await self.activate(account_id, activated_by)
                count += 1
        logger.info("전체 계좌 활성화: %d개", count)
        return count

    # ── 브로커 인스턴스 ──────────────────────────────────

    async def get_broker(self, account_id: str) -> BrokerAdapter:
        """계좌의 BrokerAdapter 인스턴스를 반환. lazy init + 캐싱.

        Raises:
            AccountNotFoundError: 계좌를 찾을 수 없음.
            InvalidBrokerTypeError: broker_type이 BROKER_REGISTRY에 등록되지 않음.
        """
        if account_id in self._brokers:
            return self._brokers[account_id]

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
        }

        broker = broker_cls(config)
        self._brokers[account_id] = broker
        logger.info(
            "브로커 인스턴스 생성: %s (type=%s)",
            account_id,
            account.broker_type,
        )
        return broker

    # ── 기본 테스트 계좌 ──────────────────────────────────

    async def create_default_test_account(self) -> Account:
        """테스트 계좌 자동 생성. 이미 존재하면 기존 계좌 반환."""
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
            credentials={},
            buy_commission_rate=preset.buy_commission_rate,
            sell_commission_rate=preset.sell_commission_rate,
        )
        return await self.create(account)


# ── 유틸리티 ──────────────────────────────────────────


def _row_to_account(row: dict[str, Any]) -> Account:
    """DB 행을 Account 객체로 변환."""
    credentials_raw = row.get("credentials", "{}")
    if isinstance(credentials_raw, str):
        credentials = decrypt_credentials(credentials_raw)
    else:
        credentials = credentials_raw

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
