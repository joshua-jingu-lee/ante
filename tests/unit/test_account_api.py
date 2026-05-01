"""Account REST API 단위 테스트."""

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
    """테스트용 BrokerAdapter 모의.

    `connect()`가 호출되면 `is_connected`가 True가 된다. `fail_connect`가
    True면 RuntimeError를 던져 실패 경로를 재현한다.
    """

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
    """테스트용 AccountService 모의 객체."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._audit_logs: list[dict[str, Any]] = []
        self._deleted: set[str] = set()
        self._brokers: dict[str, FakeBrokerAdapter] = {}
        # 테스트가 다음 get_broker 호출에서 실패하는 어댑터를 받도록 하고
        # 싶을 때 계좌 ID를 넣는다.
        self._fail_connect_for: set[str] = set()

    async def create(self, account: Account) -> Account:
        if account.account_id in self._accounts:
            from ante.account.errors import AccountAlreadyExistsError

            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다."
            )
        from ante.account.presets import BROKER_PRESETS

        if account.broker_type not in BROKER_PRESETS:
            raise InvalidBrokerTypeError(
                f"유효하지 않은 broker_type: '{account.broker_type}'"
            )
        # credentials 필수 키 검증
        preset = BROKER_PRESETS[account.broker_type]
        missing = [
            k for k in preset.required_credentials if k not in account.credentials
        ]
        if missing:
            from ante.account.errors import MissingCredentialsError

            raise MissingCredentialsError(
                f"필수 credentials 누락: {missing}. "
                f"broker_type '{account.broker_type}'에 필요: "
                f"{preset.required_credentials}"
            )
        now = datetime.now(UTC)
        account.created_at = now
        account.updated_at = now
        self._accounts[account.account_id] = account
        return account

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        accounts = list(self._accounts.values())
        if status is not None:
            accounts = [a for a in accounts if a.status == status]
        return accounts

    # 실제 AccountService.update와 동일한 분류로 비구조 필드를 다룬다.
    # 라우트는 STRUCTURAL_FIELDS를 cold-path 409로 사전 차단하므로, fake는
    # service.update가 비구조 분기에 forward 받을 수 있는 키 집합만 다룬다.
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

    async def update(self, account_id: str, **fields: Any) -> Account:
        from ante.account.errors import AccountImmutableFieldError

        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )

        # 실제 service와 동일하게 IMMUTABLE/unknown 필드를 거부한다.
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

    async def suspend(self, account_id: str, reason: str, suspended_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        from ante.account.errors import AccountAlreadySuspendedError

        if self._accounts[account_id].status == AccountStatus.SUSPENDED:
            raise AccountAlreadySuspendedError(
                f"이미 정지된 계좌입니다: '{account_id}'"
            )
        self._accounts[account_id].status = AccountStatus.SUSPENDED

    async def activate(self, account_id: str, activated_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 활성화할 수 없습니다."
            )
        account.status = AccountStatus.ACTIVE

    async def delete(self, account_id: str, deleted_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        self._accounts[account_id].status = AccountStatus.DELETED
        self._deleted.add(account_id)
        del self._accounts[account_id]

    async def get_broker(self, account_id: str) -> Any:
        """브로커 인스턴스 반환 모의. connect() 가능한 어댑터를 캐싱해서 돌려준다."""
        account = await self.get(account_id)
        # test, kis-domestic만 등록됨
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
    """테스트용 감사 로거."""

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
    account_id: str = "test-account",
    broker_type: str = "test",
) -> Account:
    """테스트용 Account 생성 헬퍼."""
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=TradingMode.VIRTUAL,
        broker_type=broker_type,
        credentials={"secret_key": "hidden"},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListAccounts:
    """GET /api/accounts."""

    def test_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == []

    def test_list_with_accounts(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["account_id"] == "test-account"

    def test_list_filter_by_status(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        a1 = _make_account("a1")
        a2 = _make_account("a2")
        a2.status = AccountStatus.SUSPENDED
        account_service._accounts["a1"] = a1
        account_service._accounts["a2"] = a2

        resp = client.get("/api/accounts?status=active")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["account_id"] == "a1"

    def test_list_invalid_status(self, client: TestClient) -> None:
        resp = client.get("/api/accounts?status=invalid")
        assert resp.status_code == 400


class TestCreateAccount:
    """POST /api/accounts.

    런타임 Web API에서 계좌 생성은 cold-path 전용이므로 항상 409로 차단된다.
    서비스 단의 회귀 보호(중복/missing credentials/broker connect 등)는
    `tests/unit/test_account.py`의 `test_create_account`,
    `test_create_duplicate_raises`, `test_create_invalid_broker_type_raises`,
    `test_create_missing_credentials_raises`,
    `test_create_partial_credentials_raises` 등이 담당한다.
    """

    def test_create_blocked_runtime_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """런타임 POST /api/accounts는 cold-path 409로 즉시 차단된다.

        - 응답 status 409
        - detail에 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER` 포함
        - AccountService는 호출되지 않아 계좌가 만들어지지 않음
        - audit 로그도 남기지 않음
        """
        resp = client.post(
            "/api/accounts",
            json={
                "account_id": "new-test",
                "name": "런타임 생성 시도",
                "broker_type": "test",
                "credentials": {"app_key": "k", "app_secret": "s"},
            },
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        # 서비스 미호출 — 계좌가 생성되지 않았다.
        assert account_service._accounts == {}
        assert account_service._brokers == {}
        # audit 로그도 남기지 않는다.
        create_logs = [
            log for log in audit_logger.logs if log["action"] == "account.create"
        ]
        assert create_logs == []

    def test_create_blocked_with_empty_body_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """빈 body여도 422가 아니라 409로 차단된다.

        라우트는 body schema를 받지 않으므로 FastAPI의 body validation
        단계가 사라져 입력 valid 여부와 무관하게 cold-path 409가 일관되게
        반환된다.
        """
        resp = client.post("/api/accounts", json={})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert account_service._accounts == {}
        assert account_service._brokers == {}
        create_logs = [
            log for log in audit_logger.logs if log["action"] == "account.create"
        ]
        assert create_logs == []

    def test_create_blocked_with_invalid_body_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """알 수 없는 키만 들어간 body여도 422가 아니라 409로 차단된다.

        cold-path 가드는 모든 입력 형태에 대해 같은 409 응답을 보장한다.
        """
        resp = client.post("/api/accounts", json={"unknown": "x"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert account_service._accounts == {}
        assert account_service._brokers == {}
        create_logs = [
            log for log in audit_logger.logs if log["action"] == "account.create"
        ]
        assert create_logs == []

    def test_create_account_returns_409_without_account_service(self) -> None:
        """AccountService가 미주입된 환경에서도 503이 아니라 409여야 한다.

        invariant I1: 핸들러는 어떤 의존성보다 먼저 cold-path 409를 raise해야
        하므로, ``app.state.account_service``가 None이어도 503으로 새지 않는다.
        ``get_account_service`` 의존성을 시그니처에서 제거한 게 회귀 차단의
        본질이며, 이 테스트가 그 invariant를 직접 단언한다.
        """
        app = create_app()  # account_service 미주입
        # account_service 미주입 확인
        assert getattr(app.state, "account_service", None) is None
        with TestClient(app) as bare_client:
            resp = bare_client.post(
                "/api/accounts",
                json={
                    "account_id": "x",
                    "name": "x",
                    "broker_type": "test",
                },
            )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail


class TestGetAccount:
    """GET /api/accounts/:id."""

    def test_get_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts/test-account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["account_id"] == "test-account"

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/accounts/nonexistent")
        assert resp.status_code == 404

    def test_account_no_credentials_in_response(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """응답에 credentials가 포함되지 않아야 한다."""
        account = _make_account()
        account.credentials = {"app_key": "secret123", "app_secret": "secret456"}
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts/test-account")
        assert resp.status_code == 200
        data = resp.json()
        assert "credentials" not in data["account"]


class TestUpdateAccount:
    """PUT /api/accounts/:id.

    비구조 필드(`name`, `timezone`, `trading_hours_start`, `trading_hours_end`)는
    런타임 PUT 200 경로를 유지한다. structural 필드(`credentials`,
    `broker_config`, `buy_commission_rate`, `sell_commission_rate`,
    `broker_type`, `exchange`, `currency`, `trading_mode`)가 포함되면
    cold-path 409로 즉시 차단된다.

    Service-layer 회귀 보호처:
    - `tests/unit/test_account_immutable_fields.py`의
      `test_update_immutable_*`, `test_update_mutable_*`
    - `tests/unit/test_account.py`의
      `test_update_credentials_invalidates_broker_cache`,
      `test_update_broker_config_invalidates_broker_cache`,
      `test_update_commission_rate_invalidates_broker_cache`,
      `test_update_preserves_cache_when_new_broker_connect_fails`
    503 매핑(`BrokerReconnectFailedError`) 회귀는 라우트 가드가 credentials를
    409로 차단해 도달할 수 없으므로 라우트 레벨 테스트는 제거. 매핑 자체는
    코드 inspection(`update_account`의 `except BrokerReconnectFailedError`)으로
    확인한다.
    """

    def test_update_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": "변경된 이름"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["name"] == "변경된 이름"
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ]
        assert len(route_logs) == 1

    def test_update_non_structural_fields_succeed(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """`timezone`, `trading_hours_start`, `trading_hours_end` 동시 변경 200."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={
                "timezone": "America/New_York",
                "trading_hours_start": "09:30",
                "trading_hours_end": "16:00",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["timezone"] == "America/New_York"
        assert data["account"]["trading_hours_start"] == "09:30"
        assert data["account"]["trading_hours_end"] == "16:00"

    def test_update_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/accounts/nonexistent",
            json={"name": "변경"},
        )
        assert resp.status_code == 404

    def test_update_no_fields(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put("/api/accounts/test-account", json={})
        assert resp.status_code == 422

    def test_update_credentials_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """`credentials` 변경 요청은 cold-path 409로 즉시 차단된다."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"credentials": {"app_key": "new", "app_secret": "new"}},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail
        # service 미호출 — 계좌 필드가 변경되지 않음
        assert account_service._accounts["test-account"].credentials == {
            "secret_key": "hidden"
        }
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_broker_config_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"broker_config": {"is_paper": True}},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "broker_config" in detail

    def test_update_buy_commission_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"buy_commission_rate": 0.001},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "buy_commission_rate" in detail

    def test_update_sell_commission_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"sell_commission_rate": 0.002},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "sell_commission_rate" in detail

    def test_update_broker_type_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"broker_type": "kis-domestic"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "broker_type" in detail

    def test_update_exchange_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"exchange": "KRX"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "exchange" in detail

    def test_update_currency_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"currency": "USD"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "currency" in detail

    def test_update_trading_mode_blocked_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"trading_mode": "live"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "trading_mode" in detail

    def test_update_blocks_when_structural_field_is_null_explicitly(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """structural 필드가 명시적으로 null이어도 cold-path 409로 차단된다.

        invariant I4: 가드는 검증된 Pydantic 값(``is not None``)이 아니라 raw
        body의 키 존재 여부로 판정한다. ``credentials: null``이라도 키가 등장
        했다는 사실이 cold-path 위반이며, Pydantic이 None으로 정규화한다고
        해서 우회되어선 안 된다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account
        original_name = account.name

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": "변경 시도", "credentials": None},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail
        # 비구조 필드(name)도 함께 차단되었는지 확인 — service.update 미호출.
        assert account_service._accounts["test-account"].name == original_name
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_blocks_when_structural_field_has_type_error(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """structural 필드 타입이 잘못돼도 422가 아니라 409로 차단된다.

        invariant I4: 가드는 Pydantic 검증보다 먼저 raw 키만 확인하므로,
        ``buy_commission_rate: "bad"``처럼 타입이 어긋나도 cold-path 409가
        나와야 한다. 만약 422가 먼저 나온다면 cold-path 가드가 schema
        validation에 의해 우회되는 상황이다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"buy_commission_rate": "bad"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "buy_commission_rate" in detail
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_blocks_when_payload_has_unknown_structural_extras(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """structural 키와 unknown 키가 섞여도 cold-path 409가 우선한다.

        Pydantic이 무시할 미지의 필드와 structural 키가 같이 와도,
        키 존재 여부 가드가 먼저 동작해 409를 보장한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"unknown_field": "x", "exchange": "KRX"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "exchange" in detail

    def test_update_unknown_mutable_field_rejected_at_route(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """알 수 없는 비구조 필드는 라우트가 명시적으로 422로 reject한다(이슈 #1153).

        이슈 #1153은 PUT 핸들러를 raw body 파싱 + structural 가드(I1/I4) +
        Content-Type 415 게이트 + mutable 검증 순서로 재구성하면서, unknown
        키에 대해 ``mutable_payload_in`` 단계에서 ``MUTABLE_FIELDS`` 화이트
        리스트와 비교하여 422 "알 수 없는 필드가 포함되었습니다"로 명시적
        reject한다. 그 결과 codegen이 ``additionalProperties: False``로 표현
        한 contract와 런타임 응답이 1:1 정합한다.

        service.update는 호출되지 않으며, unknown field가 DB에 도달할 가능성
        도 차단된다.

        service-layer 회귀 보호처(별도 invariant):
        ``tests/unit/test_account_immutable_fields.py``의
        ``test_update_unknown_field_raises_value_error``.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"some_unknown_field": "x"},
        )
        # 라우트 단 422 — unknown field가 명시적으로 reject된다.
        assert resp.status_code == 422
        body = resp.json()
        assert "some_unknown_field" in body.get("detail", "")
        # service.update 미호출 — DB 오염 차단.
        assert account_service._accounts["test-account"].name == "테스트 계좌"
        # audit 미발행
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_invalid_mutable_field_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """비구조 필드의 type이 잘못되면 422 (P1 회귀 보호).

        ``timezone``은 문자열이어야 한다. dict가 들어오면 라우트의
        ``AccountUpdateRequest.model_validate``가 ``ValidationError``를
        발생시키고, 라우트는 이를 명시적으로 422로 매핑한다. 잘못된 값이
        service/DB까지 도달해 상태를 오염시키는 것을 차단한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": {}},
        )
        assert resp.status_code == 422
        # service.update 미호출 — timezone 보존
        assert account_service._accounts["test-account"].timezone == "Asia/Seoul"
        # audit 미발행
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_invalid_name_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """``name``에 dict가 들어오면 422 (P1 회귀 보호)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": {"nested": "x"}},
        )
        assert resp.status_code == 422
        # service.update 미호출 — name 보존
        assert account_service._accounts["test-account"].name == "테스트 계좌"

    def test_update_null_mutable_value_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """``{"name": null}``은 fields가 비어 422로 차단된다 (P1 회귀 보호 + #1152).

        ``AccountUpdateRequest`` 모든 필드는 ``str | None = None``이라 null도
        Pydantic 검증을 통과한다. 그러나 ``model_dump(exclude_none=True)``로
        None 필드를 제외하면 fields가 비고, 라우트는 422 "수정할 필드가
        없습니다."로 응답한다 — null이 service까지 forward되어 DB의 name을
        지우거나 NOT NULL 제약 위반을 일으킬 가능성을 차단한다(#1152: 400 → 422
        정렬).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account
        original_name = account_service._accounts[account.account_id].name

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": None},
        )
        assert resp.status_code == 422
        assert resp.json().get("detail") == "수정할 필드가 없습니다."
        # service.update 미호출 — name 보존 (DB 오염 차단)
        assert account_service._accounts["test-account"].name == original_name
        # audit 미발행
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_invalid_json_body_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """JSON 파싱 자체가 실패하면 422.

        body가 ``dict[str, Any] | None``이므로 FastAPI의 자동
        ``RequestValidationError`` 처리가 422를 보장한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_update_non_dict_json_body_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """JSON object가 아닌 body(예: 배열, 문자열)는 422.

        body가 ``dict[str, Any] | None``으로 선언되어 있으므로 FastAPI가
        non-dict JSON을 자동 422로 처리한다 — structural 키 가드와 mutable
        schema 검증 모두 dict 가정에 의존하기 때문이다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json=["array", "not", "object"],
        )
        assert resp.status_code == 422

    def test_update_blocks_when_structural_with_invalid_mutable_returns_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """structural 키 + 잘못된 mutable 타입이 같이 와도 cold-path 409 우선.

        구조 필드 가드는 service.update 호출보다 먼저 실행되어야 한다 —
        ``credentials`` 키가 등장한 시점에 cold-path 위반이 확정되며, 같은
        페이로드에 비구조 필드가 있어도 응답은 409여야 한다. service.update는
        호출되지 않으므로 비구조 필드도 변경되지 않는다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"credentials": {"app_key": "x"}, "timezone": {}},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail
        # service.update 미호출 — 계좌 timezone 보존
        assert account_service._accounts["test-account"].timezone == "Asia/Seoul"
        # audit 미발행
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []

    def test_update_blocks_when_structural_without_account_service(self) -> None:
        """AccountService 미주입 환경에서도 structural body는 503이 아니라 409.

        attempt 5의 P3 회귀 보호: PUT 핸들러 시그니처가
        ``Depends(get_account_service)``를 들고 있으면 FastAPI가 핸들러 진입
        *전* 의존성을 평가해 service 미주입 시 503을 선행한다. 그 결과
        structural body가 들어와도 cold-path 가드(invariant I1/I4)에 도달하지
        못해 503이 응답된다.

        attempt 6은 PUT의 ``account_service``를
        ``request.app.state.account_service``로 lazy 해소해 structural 분기에서
        service에 의존하지 않도록 한다. 이 테스트가 그 invariant를 직접
        단언한다 — service 미주입 + ``credentials`` body → 409.
        """
        app = create_app()  # account_service 미주입
        assert getattr(app.state, "account_service", None) is None
        with TestClient(app) as bare_client:
            resp = bare_client.put(
                "/api/accounts/some-id",
                json={"credentials": {"app_key": "x"}},
            )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail

    def test_update_returns_503_for_mutable_when_service_missing(self) -> None:
        """service 미주입 + 비구조 body → 503 (attempt 6의 명시적 트레이드오프).

        cold-path 가드를 통과한 분기는 ``app.state.account_service``를
        lazy하게 가져온다. 미주입이면 503으로 응답한다 — 이 동작은 attempt 6의
        invariant I1 회복(structural body → 409)과 짝을 이룬다.
        """
        app = create_app()  # account_service 미주입
        assert getattr(app.state, "account_service", None) is None
        with TestClient(app) as bare_client:
            resp = bare_client.put(
                "/api/accounts/some-id",
                json={"name": "변경"},
            )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Account service not available"

    # ── 이슈 #1153: PUT request body schema accuracy + Content-Type 415 게이트 ──
    #
    # 핸들러 단계 순서(이슈 #1153 Implementation Plan)와 1:1 매핑되는 19개
    # 시나리오. structural 가드(I1/I4)는 어떤 Content-Type/payload 형태에서도
    # 우선 적용되며, Content-Type 415 게이트는 dict payload + 비어 있지 않은
    # mutable payload + non-structural 키만 들어온 경로에서 활성화된다.
    #
    # 호환성 보존(이슈 #1153 제약): 빈 body / `{}` / `{"name": null}` 의미는
    # 기존 400 no-op 유지(#1152 후속에서 422로 정렬).

    # ── structural priority (단계 5: I4 우선) ─────────────────────

    def test_update_structural_without_content_type_returns_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """structural body + Content-Type 부재 → 409 (cold-path 우선)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"credentials": {"app_key": "x"}}',
            # Content-Type 헤더 없음 — TestClient는 명시 미설정 시 보내지 않음
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail

    def test_update_structural_with_text_plain_returns_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """structural body + Content-Type: text/plain → 409.

        invariant: structural 가드는 Content-Type 415 게이트보다 *먼저*
        실행되어야 한다(I4 우선). 같은 payload가 415로 새면 cold-path 가드가
        Content-Type 검증에 의해 우회되는 회귀다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"credentials": {"app_key": "x"}}',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail

    def test_update_structural_null_value_returns_409_via_raw_key(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """structural raw key + null value(예: `{"credentials": null}`) → 409.

        invariant I4 회귀 유지(#1140): 가드는 Pydantic 검증된 ``is not None``
        값이 아니라 raw body의 키 존재 여부로 판정한다. 이 시나리오는 #1140
        에서 도입된 raw key 가드가 신규 raw body 파싱 흐름에서도 보존되는지
        확인한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"credentials": None},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail

    # ── 빈 body / `{}` / `{"name": null}` no-op 호환 ─────────────

    def test_update_empty_body_without_content_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """빈 body(b"") + Content-Type 부재 → 422 no-op (단계 2 → 6, #1152).

        호환성 보존: 클라이언트가 빈 body로 PUT을 보내면 기존과 동일한 detail
        텍스트("수정할 필드가 없습니다.")를 받지만 status는 #1152로 422
        Unprocessable Entity로 정렬되었다. Content-Type 검사·JSON 파싱을
        모두 건너뛰고 mutable 단계로 흐른 뒤 ``len(payload) == 0``로 떨어진다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"",
        )
        assert resp.status_code == 422
        assert resp.json().get("detail") == "수정할 필드가 없습니다."

    def test_update_empty_object_with_json_content_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """`{}` + Content-Type: application/json → 422 no-op (단계 6, #1152)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put("/api/accounts/test-account", json={})
        assert resp.status_code == 422
        assert resp.json().get("detail") == "수정할 필드가 없습니다."

    def test_update_empty_object_with_text_plain_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """`{}` + Content-Type: text/plain → 422 no-op (단계 6, #1152).

        명시적 빈 dict는 Content-Type과 무관하게 단계 6의 no-op 분기에서 422로
        떨어진다(단계 6이 단계 7 Content-Type 게이트보다 앞).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422
        assert resp.json().get("detail") == "수정할 필드가 없습니다."

    def test_update_name_null_with_json_content_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """`{"name": null}` + Content-Type: application/json → 422 (단계 9, #1152).

        ``model_dump(exclude_none=True)``가 결과를 비워 mutable 검증 후
        422로 떨어진다(P1 회귀 보호 유지 + #1152: 400 → 422 정렬).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": None},
        )
        assert resp.status_code == 422
        assert resp.json().get("detail") == "수정할 필드가 없습니다."

    def test_update_name_null_with_text_plain_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """`{"name": null}` + Content-Type: text/plain → 415 (단계 7 게이트 우선).

        ``len(payload) > 0`` 분기에서는 Content-Type 415 게이트가 활성화된다.
        호환성 보존 범위는 application/json 또는 빈 body에 한정되며, 비-JSON
        Content-Type은 Content-Type 자체 위반으로 415가 선행한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"name": null}',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    # ── mutable + Content-Type 415 게이트 (단계 7) ────────────────

    def test_update_missing_content_type_with_mutable_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """Content-Type 부재 + mutable body → 415."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"name": "x"}',
        )
        assert resp.status_code == 415

    def test_update_text_plain_with_mutable_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """Content-Type: text/plain + mutable body → 415."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"name": "x"}',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    def test_update_charset_suffix_passes(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """Content-Type: application/json; charset=utf-8 → 200 통과 (단계 7).

        media type 비교는 `;` 앞부분 lowercase 매칭이므로 charset suffix는
        정상 통과해야 한다(브라우저/axios 기본 변형 호환).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'{"name": "charset suffix"}',
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["name"] == "charset suffix"

    # ── parse 실패 (단계 3) ──────────────────────────────────

    def test_update_non_utf8_bytes_with_json_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """non-UTF-8 bytes + Content-Type: application/json → 422 (parse 실패)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"\xff\xfe\xfd",  # invalid UTF-8
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_update_non_utf8_bytes_with_text_plain_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """non-UTF-8 bytes + Content-Type: text/plain → 415.

        parse 실패 + 비-application/json Content-Type → 415 (Content-Type
        자체가 더 정보량 있는 위반).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"\xff\xfe\xfd",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    def test_update_invalid_json_with_json_content_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """invalid JSON + Content-Type: application/json → 422 (parse 실패)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_update_invalid_json_with_text_plain_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """invalid JSON + Content-Type: text/plain → 415."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b"not-valid-json",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    # ── non-dict JSON (단계 4) ────────────────────────────

    def test_update_array_json_with_json_content_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """non-dict JSON(`[]`) + Content-Type: application/json → 422."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json=["array", "not", "object"],
        )
        assert resp.status_code == 422

    def test_update_array_json_with_text_plain_returns_415(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """non-dict JSON + Content-Type: text/plain → 415."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            content=b'["array"]',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    # ── unknown 키 + mutable type (단계 8) ───────────────

    def test_update_unknown_mutable_key_with_json_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """unknown mutable key(`{"foo": "bar"}`) → 422 (additionalProperties: False)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"foo": "bar"},
        )
        assert resp.status_code == 422
        assert "foo" in resp.json().get("detail", "")

    # ── service-layer fallback (#1144 defense-in-depth) ──

    def test_put_update_route_translates_runtime_exception_to_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """라우트 1차 가드(I1/I4)를 우회한 경로에서 service가 직접
        ``AccountStructuralChangeRequiresStoppedServerError``를 raise해도
        라우트가 409 + cold-path detail로 매핑한다 (#1144 defense-in-depth).

        시나리오: 정상 mutable payload(``{"name": "..."}``)가 들어와 라우트의
        structural 가드를 통과한 뒤 ``account_service.update``가 새 예외를
        raise하도록 monkeypatch한다. 정상 흐름에서는 service의
        ``_runtime_started`` 플래그와 STRUCTURAL_FIELDS 검사로 mutable-only
        호출은 통과되지만, 본 회귀 테스트는 매핑 자체를 강제한다.
        """
        from ante.account.errors import (
            AccountStructuralChangeRequiresStoppedServerError,
        )

        account = _make_account()
        account_service._accounts[account.account_id] = account

        async def raise_runtime_guard(account_id: str, **fields: Any) -> Account:
            raise AccountStructuralChangeRequiresStoppedServerError(
                "다음 필드는 cold-path 전용입니다: credentials"
            )

        # mutable-only payload는 라우트 가드(I1/I4)를 통과한다 — 그 뒤 service의
        # 가짜 예외가 활성화되도록 monkeypatch.
        account_service.update = raise_runtime_guard  # type: ignore[method-assign]

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": "변경 시도"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        assert "credentials" in detail
        # service-layer raise 경로에서는 audit log가 남지 않는다.
        assert [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ] == []


# PUT requestBody schema accuracy(mutable 모델 노출)는 issue #1153에서 처리됨.


class TestSuspendAccount:
    """POST /api/accounts/:id/suspend."""

    def test_suspend_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.post(
            "/api/accounts/test-account/suspend",
            json={"reason": "테스트 정지"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["status"] == "suspended"
        assert "정지" in data["message"]
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.suspend"
        ]
        assert len(route_logs) == 1

    def test_suspend_without_body(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """body 없이 POST 호출 시에도 200을 반환해야 한다 (GH-640)."""
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.post("/api/accounts/test-account/suspend")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["status"] == "suspended"

    def test_suspend_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/accounts/nonexistent/suspend",
            json={"reason": "없는 계좌"},
        )
        assert resp.status_code == 404

    def test_suspend_already_suspended_returns_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """이미 정지된 계좌를 재정지하면 409 Conflict를 반환해야 한다 (GH-651)."""
        account = _make_account()
        account.status = AccountStatus.SUSPENDED
        account_service._accounts[account.account_id] = account

        resp = client.post(
            "/api/accounts/test-account/suspend",
            json={"reason": "재정지 시도"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert "이미 정지된 계좌" in data["detail"]


class TestActivateAccount:
    """POST /api/accounts/:id/activate."""

    def test_activate_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account.status = AccountStatus.SUSPENDED
        account_service._accounts[account.account_id] = account

        resp = client.post("/api/accounts/test-account/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["status"] == "active"
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.activate"
        ]
        assert len(route_logs) == 1

    def test_activate_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/accounts/nonexistent/activate")
        assert resp.status_code == 404

    def test_activate_deleted_returns_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account.status = AccountStatus.DELETED
        account_service._accounts[account.account_id] = account

        resp = client.post("/api/accounts/test-account/activate")
        assert resp.status_code == 409


class TestDeleteAccount:
    """DELETE /api/accounts/:id.

    런타임 Web API에서 계좌 삭제는 cold-path 전용이므로 항상 409로 차단된다.
    Service-layer 회귀 보호처: `tests/unit/test_account.py::test_delete_account`,
    `tests/unit/test_account.py::test_delete_already_deleted_account_raises`.
    """

    def test_delete_blocked_runtime_409(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """런타임 DELETE /api/accounts/:id는 cold-path 409로 즉시 차단된다.

        - 응답 status 409
        - detail에 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER` 포함
        - AccountService는 호출되지 않음 (`_accounts`/`_deleted` 변경 없음)
        - audit 로그 미발행
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.delete("/api/accounts/test-account")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
        # 서비스 미호출 — 계좌 그대로 유지, soft-delete 트래킹도 변경 없음
        assert "test-account" in account_service._accounts
        assert account_service._deleted == set()
        assert [
            log for log in audit_logger.logs if log["action"] == "account.delete"
        ] == []

    def test_delete_account_returns_409_without_account_service(self) -> None:
        """AccountService가 미주입된 환경에서도 503이 아니라 409여야 한다.

        invariant I1: DELETE 핸들러도 ``get_account_service`` 의존성을 거치지
        않아야 하며, account_service가 None일 때도 cold-path 409가 일관되게
        반환되어야 한다.
        """
        app = create_app()  # account_service 미주입
        assert getattr(app.state, "account_service", None) is None
        with TestClient(app) as bare_client:
            resp = bare_client.delete("/api/accounts/some-id")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in detail
