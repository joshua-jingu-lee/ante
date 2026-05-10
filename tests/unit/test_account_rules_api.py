"""Account Rules REST API 단위 테스트.

GET /api/accounts/{account_id}/rules
PUT /api/accounts/{account_id}/rules/{rule_type}

#1376: PUT 라우트는 master 인증 가드(``require_master_caller``)가 적용되어
``master-token`` Bearer 헤더 없이 호출하면 401 이 떨어진다. 기존 PUT 테스트는
``_MASTER_HEADERS`` fixture 헤더를 부여해 라우트 contract 변경(이슈 #1376)에
맞춘다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import AccountNotFoundError  # noqa: E402
from ante.account.models import Account, AccountStatus, TradingMode  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1376 update_account_rule 인증 가드) ────────────


@dataclass
class _FakeMember:
    member_id: str
    type: str = "human"
    role: str = "master"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _FakeMemberService:
    """``require_master_caller`` 통과를 위한 최소 stub (#1376).

    ``master-token`` Bearer 또는 ``master-session-id`` 쿠키로 master 호출자를
    인식한다. 기존 valid PUT / 404 / 422 케이스는 ``_MASTER_HEADERS`` fixture
    에 묶어 #1376 가드와 정합시킨다.
    """

    def __init__(self) -> None:
        self._members = {
            "master-user": _FakeMember(member_id="master-user"),
        }
        self._tokens = {
            "master-token": "master-user",
        }

    async def authenticate(self, token: str) -> _FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _FakeMember | None:
        return self._members.get(member_id)


class _FakeSessionService:
    def __init__(self) -> None:
        self._sessions = {"master-session-id": "master-user"}

    async def validate(self, session_id: str) -> dict | None:
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-05-09 00:00:00"}


# #1376: master 인증 헤더 fixture. 모든 PUT 호출은 본 헤더를 기본으로 사용한다.
_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


class FakeAccountService:
    """테스트용 AccountService 모의 객체."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        return list(self._accounts.values())


class FakeAuditLogger:
    """테스트용 감사 로거."""

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)


class FakeDynamicConfig:
    """테스트용 DynamicConfigService 모의 객체."""

    _MISSING = object()

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str, default: Any = _MISSING) -> Any:
        if key not in self._store:
            if default is not self._MISSING:
                return default
            from ante.config.exceptions import ConfigError

            raise ConfigError(f"Dynamic config not found: {key}")
        return self._store[key]

    async def set(
        self, key: str, value: Any, category: str, changed_by: str = "system"
    ) -> None:
        self._store[key] = value

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def get_all(self) -> list[dict[str, Any]]:
        return [{"key": k, "value": v} for k, v in self._store.items()]


class FakeConfig:
    """테스트용 정적 Config 모의 객체."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _make_account(account_id: str = "test-account") -> Account:
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        credentials={},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _add_account(service: FakeAccountService, account_id: str = "acct-1") -> Account:
    """테스트용 계좌를 직접 삽입하는 헬퍼."""
    account = _make_account(account_id)
    service._accounts[account_id] = account
    return account


@pytest.fixture
def account_service() -> FakeAccountService:
    return FakeAccountService()


@pytest.fixture
def audit_logger() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def dynamic_config() -> FakeDynamicConfig:
    return FakeDynamicConfig()


@pytest.fixture
def static_config() -> FakeConfig:
    return FakeConfig()


@pytest.fixture
def member_service() -> _FakeMemberService:
    return _FakeMemberService()


@pytest.fixture
def session_service() -> _FakeSessionService:
    return _FakeSessionService()


@pytest.fixture
def app(
    account_service: FakeAccountService,
    audit_logger: FakeAuditLogger,
    dynamic_config: FakeDynamicConfig,
    static_config: FakeConfig,
    member_service: _FakeMemberService,
    session_service: _FakeSessionService,
):
    return create_app(
        account_service=account_service,
        audit_logger=audit_logger,
        dynamic_config=dynamic_config,
        config=static_config,
        member_service=member_service,
        session_service=session_service,
    )


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


class TestGetAccountRules:
    """GET /api/accounts/{account_id}/rules."""

    def test_account_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/accounts/nonexistent/rules")
        assert resp.status_code == 404

    def test_empty_rules(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-1"
        assert data["rules"] == []

    def test_rules_from_dynamic_config(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")
        dynamic_config._store["accounts.acct-1.rules"] = [
            {
                "type": "daily_loss_limit",
                "enabled": True,
                "max_daily_loss_percent": 0.05,
            },
            {
                "type": "trading_hours",
                "enabled": False,
                "allowed_hours": "09:00-15:30",
            },
        ]

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 2
        assert data["rules"][0]["type"] == "daily_loss_limit"
        assert data["rules"][0]["enabled"] is True
        assert data["rules"][0]["params"]["max_daily_loss_percent"] == 0.05
        assert data["rules"][1]["type"] == "trading_hours"
        assert data["rules"][1]["enabled"] is False

    def test_rules_from_static_config_fallback(
        self,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """DynamicConfig에 없으면 정적 Config에서 읽는다."""
        _add_account(account_service, "acct-1")

        static_config = FakeConfig(
            {
                "accounts.acct-1.rules": [
                    {
                        "type": "total_exposure_limit",
                        "enabled": True,
                        "max_exposure_percent": 0.20,
                    },
                ]
            }
        )
        app = create_app(
            account_service=account_service,
            audit_logger=audit_logger,
            dynamic_config=FakeDynamicConfig(),
            config=static_config,
        )
        client = TestClient(app)

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["type"] == "total_exposure_limit"
        assert data["rules"][0]["params"]["max_exposure_percent"] == 0.20

    def test_unknown_rule_types_filtered(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """RULE_REGISTRY에 없는 룰 타입은 필터링된다."""
        _add_account(account_service, "acct-1")
        dynamic_config._store["accounts.acct-1.rules"] = [
            {"type": "daily_loss_limit", "enabled": True},
            {"type": "unknown_rule_xyz", "enabled": True},
        ]

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["type"] == "daily_loss_limit"


class TestUpdateAccountRule:
    """PUT /api/accounts/{account_id}/rules/{rule_type}."""

    def test_account_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/accounts/nonexistent/rules/daily_loss_limit",
            json={"enabled": True, "params": {}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 404

    def test_unknown_rule_type(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/nonexistent_rule",
            json={"enabled": True, "params": {}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 400
        assert "nonexistent_rule" in resp.json()["detail"]

    def test_add_new_rule(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0.03}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-1"
        assert data["rule_type"] == "daily_loss_limit"
        assert data["rule"]["type"] == "daily_loss_limit"
        assert data["rule"]["enabled"] is True
        assert data["rule"]["params"]["max_daily_loss_percent"] == 0.03

        # DynamicConfig에 저장되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 1
        assert stored[0]["type"] == "daily_loss_limit"

    def test_update_existing_rule(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")

        # 기존 룰 설정
        dynamic_config._store["accounts.acct-1.rules"] = [
            {
                "type": "daily_loss_limit",
                "enabled": True,
                "max_daily_loss_percent": 0.05,
            },
            {
                "type": "trading_hours",
                "enabled": True,
            },
        ]

        # daily_loss_limit 업데이트
        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": False, "params": {"max_daily_loss_percent": 0.10}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"]["enabled"] is False
        assert data["rule"]["params"]["max_daily_loss_percent"] == 0.10

        # trading_hours는 그대로, daily_loss_limit만 변경되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 2
        daily_loss = next(r for r in stored if r["type"] == "daily_loss_limit")
        assert daily_loss["enabled"] is False
        assert daily_loss["max_daily_loss_percent"] == 0.10
        trading_hours = next(r for r in stored if r["type"] == "trading_hours")
        assert trading_hours["enabled"] is True

    def test_audit_log_created(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/position_size",
            json={"enabled": True, "params": {"max_position_percent": 0.15}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

        # AuditMiddleware도 로그를 남기므로 action으로 필터링
        rule_logs = [
            lg for lg in audit_logger.logs if lg.get("action") == "account.rule.update"
        ]
        assert len(rule_logs) == 1
        log = rule_logs[0]
        assert "position_size" in log["resource"]
        # #1376: caller_id 가 audit member_id 로 사용되어야 한다.
        assert log["member_id"] == "master-user"

    def test_all_rule_types_accepted(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """RULE_REGISTRY에 등록된 모든 룰 타입이 PUT으로 수정 가능하다."""
        from ante.rule.engine import RULE_REGISTRY

        _add_account(account_service, "acct-1")

        for rule_type in RULE_REGISTRY:
            resp = client.put(
                f"/api/accounts/acct-1/rules/{rule_type}",
                json={"enabled": True, "params": {}},
                headers=_MASTER_HEADERS,
            )
            assert resp.status_code == 200, f"Failed for rule_type={rule_type}"
            assert resp.json()["rule_type"] == rule_type

    def test_static_config_fallback_on_update(
        self,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
        member_service: _FakeMemberService,
        session_service: _FakeSessionService,
    ) -> None:
        """정적 Config에 있는 룰이 업데이트되면 DynamicConfig에 저장된다."""
        _add_account(account_service, "acct-1")

        static_config = FakeConfig(
            {
                "accounts.acct-1.rules": [
                    {
                        "type": "total_exposure_limit",
                        "enabled": True,
                        "max_exposure_percent": 0.20,
                    },
                ]
            }
        )
        dynamic_config = FakeDynamicConfig()
        app = create_app(
            account_service=account_service,
            audit_logger=audit_logger,
            dynamic_config=dynamic_config,
            config=static_config,
            member_service=member_service,
            session_service=session_service,
        )
        client = TestClient(app)

        resp = client.put(
            "/api/accounts/acct-1/rules/total_exposure_limit",
            json={"enabled": False, "params": {"max_exposure_percent": 0.30}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

        # DynamicConfig에 저장되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 1
        assert stored[0]["max_exposure_percent"] == 0.30
        assert stored[0]["enabled"] is False


class TestRuleConfigValidation:
    """PUT /api/accounts/{id}/rules/{type} — config 값 범위 검증."""

    def test_negative_max_daily_loss_percent_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """음수 max_daily_loss_percent는 422로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": -1}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_daily_loss_percent" in resp.json()["detail"]

    def test_over_one_max_daily_loss_percent_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """1 초과 max_daily_loss_percent는 422로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 1.5}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422

    def test_valid_max_daily_loss_percent_accepted(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """유효한 max_daily_loss_percent(0~1)는 정상 수락된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0.05}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

    def test_zero_max_daily_loss_percent_accepted(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """max_daily_loss_percent=0은 유효하다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

    def test_negative_max_exposure_percent_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/total_exposure_limit",
            json={"enabled": True, "params": {"max_exposure_percent": -0.5}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_exposure_percent" in resp.json()["detail"]

    def test_negative_max_exposure_amount_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/total_exposure_limit",
            json={"enabled": True, "params": {"max_exposure_amount": -1000}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_exposure_amount" in resp.json()["detail"]

    def test_negative_max_position_percent_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/position_size",
            json={"enabled": True, "params": {"max_position_percent": -0.1}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_position_percent" in resp.json()["detail"]

    def test_negative_unrealized_loss_percent_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/unrealized_loss_limit",
            json={
                "enabled": True,
                "params": {"max_unrealized_loss_percent": -0.05},
            },
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_unrealized_loss_percent" in resp.json()["detail"]

    def test_negative_max_trades_per_hour_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/trade_frequency",
            json={"enabled": True, "params": {"max_trades_per_hour": -5}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_trades_per_hour" in resp.json()["detail"]

    def test_empty_params_accepted(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """params가 비어 있으면 검증을 통과한다 (기본값 사용)."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

    def test_string_value_for_numeric_param_rejected(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """숫자 파라미터에 문자열이 전달되면 422로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": "abc"}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422


class TestRuleConfigNonFiniteRejection:
    """PUT /api/accounts/{id}/rules/{type} — NaN/Inf 거부 (#1380 oracle A7).

    인증된 master 호출이 ``params`` 안의 ``NaN`` / ``Infinity`` /
    ``-Infinity`` 같은 non-finite numeric threshold 를 200 으로 통과시키던
    회귀를 차단한다. raw body 로 ``NaN`` literal 을 보내야 한다 — httpx
    ``json=`` 은 ``allow_nan=False`` 라 numeric NaN 을 직렬화하지 못하기
    때문이다. ``json.loads`` default 는 ``NaN`` literal 을 ``float('nan')`` 으로
    파싱하므로, ``RuleUpdateRequest`` 의 ``field_validator`` 가 그 결과를 422
    로 잘라내야 한다. 422 시 ``DynamicConfig.set`` / RuleEngine reload 가
    호출되지 않아야 한다 (spy).
    """

    def test_account_rule_update_nan_threshold_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """``max_daily_loss_percent: NaN`` 은 422 로 거부되고 persist 되지 않는다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            content=b'{"enabled": true, "params": {"max_daily_loss_percent": NaN}}',
            headers={
                **_MASTER_HEADERS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        # 응답 body 가 valid JSON 으로 직렬화되어야 한다 (#1380 codex P1).
        # ``e.errors()`` 기본 출력은 ``ctx.error`` 에 ``ValueError`` 객체와
        # ``input`` 에 ``float('nan')`` 을 포함시킨다. RFC7807 핸들러
        # (``ante.web.errors``) 가 ``str(exc.detail)`` 로 stringify 하더라도,
        # sanitize 안 된 detail 에는 ``ValueError(...)`` repr 과 ``ctx`` /
        # ``input`` key 가 그대로 노출되어 클라이언트에 내부 디버그 정보가
        # 누설되며, future 핸들러가 ``detail`` 을 raw list 로 보내면 NaN 이
        # ``JSONResponse(allow_nan=False)`` 를 깨뜨려 500 으로 회귀한다.
        # 핸들러는 ``include_context=False, include_input=False`` 로 detail 을
        # sanitize 하여 순수 ``loc`` / ``msg`` 만 노출해야 한다.
        body = resp.json()
        # detail 표현은 RFC7807 핸들러에 의해 string 일 수 있다 — 어느 쪽이든
        # ``ctx`` / ``input`` / ``ValueError(`` 디버그 토큰이 노출되어서는
        # 안 된다.
        detail = body["detail"]
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert "ValueError(" not in detail_str
        assert "'ctx'" not in detail_str
        assert "'input'" not in detail_str
        # spy: 422 시 stored 가 비어 있어야 한다 (set 미호출).
        assert "accounts.acct-1.rules" not in dynamic_config._store

    def test_account_rule_update_positive_inf_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """``max_daily_loss_percent: Infinity`` 는 422 로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            content=(
                b'{"enabled": true, "params": {"max_daily_loss_percent": Infinity}}'
            ),
            headers={
                **_MASTER_HEADERS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        # 응답이 valid JSON 으로 직렬화되어야 한다 (#1380 codex P1 sanitize).
        resp.json()
        assert "accounts.acct-1.rules" not in dynamic_config._store

    def test_account_rule_update_negative_inf_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """``max_daily_loss_percent: -Infinity`` 는 422 로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            content=(
                b'{"enabled": true, "params": {"max_daily_loss_percent": -Infinity}}'
            ),
            headers={
                **_MASTER_HEADERS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        # 응답이 valid JSON 으로 직렬화되어야 한다 (#1380 codex P1 sanitize).
        resp.json()
        assert "accounts.acct-1.rules" not in dynamic_config._store

    def test_account_rule_update_nested_dict_nan_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """nested dict 안의 ``NaN`` 도 재귀적으로 거부된다.

        ``params`` 는 ``dict[str, Any]`` open object 이므로, 룰별로 nested
        struct (예: ``{"thresholds": {"warn": NaN}}``) 가 등장할 수 있다.
        helper 가 dict values 를 재귀하여 ``NaN`` 을 잡아야 한다.
        """
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            content=(b'{"enabled": true, "params": {"thresholds": {"warn": NaN}}}'),
            headers={
                **_MASTER_HEADERS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        # 응답이 valid JSON 으로 직렬화되어야 한다 (#1380 codex P1 sanitize).
        resp.json()
        assert "accounts.acct-1.rules" not in dynamic_config._store

    def test_account_rule_update_list_with_nan_returns_422(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """list 요소 안의 ``NaN`` 도 재귀적으로 거부된다."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            content=(b'{"enabled": true, "params": {"steps": [0.05, NaN, 0.10]}}'),
            headers={
                **_MASTER_HEADERS,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        # 응답이 valid JSON 으로 직렬화되어야 한다 (#1380 codex P1 sanitize).
        resp.json()
        assert "accounts.acct-1.rules" not in dynamic_config._store

    def test_account_rule_update_finite_threshold_succeeds(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """finite ``max_daily_loss_percent`` happy path 회귀 보호 (#1380)."""
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0.05}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        # finite 값은 정상 persist 되어야 한다.
        assert "accounts.acct-1.rules" in dynamic_config._store

    def test_account_rule_update_bool_param_handling(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """numeric param key 에 ``bool`` 이 오면 RULE_REGISTRY 가 422 로 거부.

        정책 (#1380):
        - schema 단 ``_reject_non_finite`` 는 ``bool`` 을 통과시킨다 (numeric
          분기에서 가로채지 않음).
        - RULE_REGISTRY ``validate_config`` 는 known numeric key 에 대해
          ``_is_finite_numeric`` 으로 ``bool`` 을 거부한다.
        - 결과: ``params={"max_daily_loss_percent": True}`` 는 RULE_REGISTRY
          단계에서 422 가 떨어진다.
        """
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": True}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert "max_daily_loss_percent" in resp.json()["detail"]
        # 422 시 persist 되지 않아야 한다.
        assert "accounts.acct-1.rules" not in dynamic_config._store


class TestRuleUpdateRequestSchema:
    """``RuleUpdateRequest`` Pydantic 단위 검증 (#1380).

    web 라우트 통합 테스트와 별도로, schema 자체가 ``NaN`` / ``Inf`` 를
    ``ValidationError`` 로 거부하는지 unit-level 로 보호한다.
    """

    def test_rule_update_request_field_validator_rejects_nan(self) -> None:
        from pydantic import ValidationError

        from ante.web.schemas import RuleUpdateRequest

        with pytest.raises(ValidationError):
            RuleUpdateRequest.model_validate(
                {
                    "enabled": True,
                    "params": {"max_daily_loss_percent": float("nan")},
                }
            )

    def test_rule_update_request_field_validator_rejects_positive_inf(self) -> None:
        from pydantic import ValidationError

        from ante.web.schemas import RuleUpdateRequest

        with pytest.raises(ValidationError):
            RuleUpdateRequest.model_validate(
                {
                    "enabled": True,
                    "params": {"max_daily_loss_percent": float("inf")},
                }
            )

    def test_rule_update_request_field_validator_rejects_negative_inf(self) -> None:
        from pydantic import ValidationError

        from ante.web.schemas import RuleUpdateRequest

        with pytest.raises(ValidationError):
            RuleUpdateRequest.model_validate(
                {
                    "enabled": True,
                    "params": {"max_daily_loss_percent": float("-inf")},
                }
            )

    def test_rule_update_request_field_validator_rejects_nested_nan(self) -> None:
        from pydantic import ValidationError

        from ante.web.schemas import RuleUpdateRequest

        with pytest.raises(ValidationError):
            RuleUpdateRequest.model_validate(
                {
                    "enabled": True,
                    "params": {"nested": {"deeper": [1.0, float("nan")]}},
                }
            )

    def test_rule_update_request_field_validator_accepts_finite(self) -> None:
        from ante.web.schemas import RuleUpdateRequest

        body = RuleUpdateRequest.model_validate(
            {
                "enabled": True,
                "params": {"max_daily_loss_percent": 0.05},
            }
        )
        assert body.params == {"max_daily_loss_percent": 0.05}

    def test_rule_update_request_field_validator_passes_bool(self) -> None:
        """``bool`` 은 schema 단에서 통과 — RULE_REGISTRY 가 별도로 거부한다."""
        from ante.web.schemas import RuleUpdateRequest

        body = RuleUpdateRequest.model_validate(
            {
                "enabled": True,
                "params": {"some_flag": True},
            }
        )
        assert body.params == {"some_flag": True}


class TestAccountRulesEffectiveMergeContract:
    """PUT API와 effective rules merge의 계약 검증 (#1296).

    PUT API는 stored(explicit overrides)만 다룬다. RuleEngine이 reload 시
    실제 적용하는 effective rules는
    ``ante.rule.defaults.resolve_effective_rules``가 broker_type별 default와
    stored를 merge한 결과다.

    회귀: KIS domestic 계좌에서 ``daily_loss_limit`` 같은 custom rule을
    PUT으로 추가했을 때, default ``trading_hours``가 effective에서 사라지면
    A7 oracle (#1296) 회귀가 재현된다. 본 테스트는 stored가
    explicit-only로 저장되되, helper가 merge하면 default + custom이 모두
    살아 있음을 검증한다.
    """

    def test_account_rules_api_put_preserves_default(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """KIS 계좌에 custom rule PUT 후 effective merge에 default가 보존된다."""
        from ante.rule.defaults import resolve_effective_rules

        # KIS domestic 계좌 등록.
        kis_account = Account(
            account_id="acct-kis",
            name="KIS 국내",
            exchange="KRX",
            currency="KRW",
            timezone="Asia/Seoul",
            trading_hours_start="09:00",
            trading_hours_end="15:30",
            trading_mode=TradingMode.VIRTUAL,
            broker_type="kis-domestic",
            credentials={},
            buy_commission_rate=Decimal("0"),
            sell_commission_rate=Decimal("0"),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        account_service._accounts["acct-kis"] = kis_account

        # custom rule PUT.
        resp = client.put(
            "/api/accounts/acct-kis/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0.05}},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

        # stored에는 explicit override만 — default trading_hours는 빠져 있다.
        stored = dynamic_config._store["accounts.acct-kis.rules"]
        stored_types = {r.get("type") for r in stored}
        assert stored_types == {"daily_loss_limit"}

        # effective merge 시 default trading_hours + custom daily_loss_limit
        # 모두 살아 있어야 한다 (#1296: reload 후에도 KIS default 보존).
        effective = resolve_effective_rules(kis_account, stored)
        effective_types = [r.get("type") for r in effective]
        assert "trading_hours" in effective_types
        assert "daily_loss_limit" in effective_types
