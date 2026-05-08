"""PUT /api/accounts/{id}의 trading_hours strict HH:MM 검증.

이슈 #1334: invalid trading_hours("99:99")가 PUT 200으로 저장되어 generic
preflight error로 주문이 반복 거부되는 문제를 422로 차단.

POST 라우트 테스트는 본 모듈 비목표 — POST는 항상 cold-path 409이며 (#1143),
이슈 #1334 plan v5의 stop condition으로 명시되어 있다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import (  # noqa: E402
    AccountDeletedError,
    AccountNotFoundError,
    InvalidBrokerTypeError,
)
from ante.account.models import Account, AccountStatus, TradingMode  # noqa: E402
from ante.web.app import create_app  # noqa: E402


class FakeBrokerAdapter:
    def __init__(self, fail_connect: bool = False) -> None:
        self.is_connected = False
        self.fail_connect = fail_connect
        self.connect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.fail_connect:
            raise RuntimeError("connect 실패 — 시뮬레이션")
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False


class FakeAccountService:
    """이슈 #1334 회귀 테스트용 AccountService 모의.

    `tests/unit/test_account_api.py::FakeAccountService`와 같은 분류 정책을
    유지한다 — 본 모듈은 PUT route 422 검증만 다루므로 분리해서 두어도
    안전하며, 라우트 가드의 결과만 단언한다.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._audit_logs: list[dict[str, Any]] = []
        self._deleted: set[str] = set()
        self._brokers: dict[str, FakeBrokerAdapter] = {}
        self._fail_connect_for: set[str] = set()
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    UPDATABLE_FIELDS = frozenset(
        {
            "name",
            "timezone",
            "trading_hours_start",
            "trading_hours_end",
            "credentials",
            "broker_config",
            "buy_commission_rate",
            "sell_commission_rate",
        }
    )
    IMMUTABLE_FIELDS = frozenset(
        {"exchange", "currency", "trading_mode", "broker_type"}
    )

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        accounts = list(self._accounts.values())
        if status is not None:
            accounts = [a for a in accounts if a.status == status]
        return accounts

    async def update(self, account_id: str, **fields: Any) -> Account:
        from ante.account.errors import AccountImmutableFieldError

        self.update_calls.append((account_id, dict(fields)))
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )
        attempted_immutable = set(fields.keys()) & self.IMMUTABLE_FIELDS
        if attempted_immutable:
            raise AccountImmutableFieldError(
                f"다음 필드는 수정할 수 없습니다: {sorted(attempted_immutable)}"
            )
        unrecognized = (
            set(fields.keys()) - self.UPDATABLE_FIELDS - self.IMMUTABLE_FIELDS
        )
        if unrecognized:
            raise ValueError(f"인식할 수 없는 필드입니다: {sorted(unrecognized)}")
        for key, value in fields.items():
            setattr(account, key, value)
        account.updated_at = datetime.now(UTC)
        return account

    async def get_broker(self, account_id: str) -> Any:
        account = await self.get(account_id)
        if account.broker_type not in ("test", "kis-domestic"):
            raise InvalidBrokerTypeError(
                f"broker_type '{account.broker_type}'은 BROKER_REGISTRY에 "
                f"등록되지 않았습니다."
            )
        if account_id not in self._brokers:
            self._brokers[account_id] = FakeBrokerAdapter(
                fail_connect=(account_id in self._fail_connect_for)
            )
        return self._brokers[account_id]


class FakeAuditLogger:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)


@pytest.fixture
def account_service() -> FakeAccountService:
    return FakeAccountService()


@pytest.fixture
def audit_logger() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def app(account_service: FakeAccountService, audit_logger: FakeAuditLogger):
    return create_app(
        account_service=account_service,
        audit_logger=audit_logger,
    )


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _make_account(
    account_id: str = "oracle-paper",
    trading_hours_start: str = "09:00",
    trading_hours_end: str = "15:30",
) -> Account:
    return Account(
        account_id=account_id,
        name="Oracle Paper",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start=trading_hours_start,
        trading_hours_end=trading_hours_end,
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        credentials={"secret_key": "hidden"},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestPutAccountTradingHoursValidation:
    """PUT /api/accounts/{id} body의 trading_hours_start/end 422 회귀 가드."""

    def test_put_account_invalid_trading_hours_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """trading_hours_start='99:99'는 422로 차단된다 (이슈 #1334 직접 회귀)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/oracle-paper",
            json={"trading_hours_start": "99:99"},
        )
        assert resp.status_code == 422
        # 422 detail에 trading_hours_start 필드가 포함되어 클라이언트가
        # 어떤 필드 때문에 거부됐는지 식별 가능해야 한다.
        assert "trading_hours_start" in str(resp.json())

    def test_put_account_empty_trading_hours_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """update 경로의 ``""``는 broker preset fallback이 없으므로 422 (#1334)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/oracle-paper",
            json={"trading_hours_end": ""},
        )
        assert resp.status_code == 422

    def test_put_account_seconds_in_trading_hours_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """초까지 포함된 '09:30:00'은 strict HH:MM이 아니므로 422 (#1334)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/oracle-paper",
            json={"trading_hours_start": "09:30:00"},
        )
        assert resp.status_code == 422

    def test_put_account_invalid_trading_hours_does_not_mutate_state(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """invalid 입력은 service.update 미호출 + 계좌 필드 보존 + audit 미발행.

        이슈 #1334의 본질적인 회귀 — invalid '99:99'가 DB로 흘러가 generic
        preflight error를 트리거하면 안 된다.
        """
        account = _make_account(
            trading_hours_start="09:00",
            trading_hours_end="15:30",
        )
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/oracle-paper",
            json={"trading_hours_start": "99:99"},
        )
        assert resp.status_code == 422
        # service.update 미호출 — 계좌 trading_hours_start 보존
        assert account_service.update_calls == []
        assert account_service._accounts["oracle-paper"].trading_hours_start == "09:00"
        assert account_service._accounts["oracle-paper"].trading_hours_end == "15:30"
        # audit 로그도 남기지 않는다
        update_logs = [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ]
        assert update_logs == []
