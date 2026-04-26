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

    async def update(self, account_id: str, **fields: Any) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )
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
        assert resp.status_code == 400

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

    def test_update_invalid_mutable_field_type_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """비구조(mutable) 필드 타입이 잘못되면 422를 반환한다 (P2 회귀 보호).

        ``timezone``은 ``str | None``인데 dict가 들어오면
        ``AccountMutableUpdateRequest.model_validate``가 ``ValidationError``를
        던지고, 라우트는 이를 422 ``HTTPException``으로 명시 변환한다.
        이전 attempt에서는 ``ValidationError``가 그대로 전파되어 클라이언트가
        FastAPI 자동 422 contract를 잃는 회귀가 있었다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": {}},
        )
        assert resp.status_code == 422
        # service.update 미호출 — 계좌 timezone 보존
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
        """``name`` 타입 오류도 422 (P2 회귀 보호).

        Pydantic은 dict → str 강제 변환을 허용하지 않으므로 422가 발생해야
        한다. 422가 아닌 다른 status는 schema validation 회귀 신호다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": {"nested": "object"}},
        )
        assert resp.status_code == 422

    def test_update_invalid_json_body_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """JSON 파싱 자체가 실패하면 422.

        FastAPI는 보통 자동 처리하지만, 이 라우트는 raw body를 직접 읽으므로
        파싱 실패 경로가 라우트 본문에서 422로 변환되는지 보장한다.
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

        라우트는 dict 형태의 raw payload만 허용한다 — structural 키 가드와
        mutable schema 검증 모두 dict 가정에 의존한다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json=["array", "not", "object"],
        )
        assert resp.status_code == 422


class TestUpdateAccountOpenAPISchema:
    """PUT /api/accounts/:id의 OpenAPI requestBody schema 노출 보호 (P3).

    런타임 mutable 4 필드만 노출하는 ``AccountMutableUpdateRequest``가
    requestBody schema로 노출되어야 한다. 이전 attempt에서는 body가
    ``dict[str, Any] | None``이라 schema accuracy를 잃었다.
    """

    def test_openapi_put_uses_mutable_update_request(
        self,
        client: TestClient,
    ) -> None:
        """OpenAPI document의 PUT requestBody가 mutable 모델을 참조한다."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()

        path = spec["paths"]["/api/accounts/{account_id}"]["put"]
        request_body_schema = path["requestBody"]["content"]["application/json"][
            "schema"
        ]
        # anyOf wrapper로 nullable 표현될 수 있다.
        if "anyOf" in request_body_schema:
            refs = [
                item.get("$ref", "")
                for item in request_body_schema["anyOf"]
                if "$ref" in item
            ]
        else:
            refs = [request_body_schema.get("$ref", "")]
        assert any("AccountMutableUpdateRequest" in ref for ref in refs), (
            f"expected AccountMutableUpdateRequest reference, got {refs}"
        )

        # mutable 모델 정의 확인 — mutable 4 필드만 노출되어야 한다.
        mutable_schema = spec["components"]["schemas"]["AccountMutableUpdateRequest"]
        properties = set(mutable_schema.get("properties", {}).keys())
        assert properties == {
            "name",
            "timezone",
            "trading_hours_start",
            "trading_hours_end",
        }


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
