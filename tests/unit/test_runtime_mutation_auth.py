"""Account/Bot/Treasury mutation route 인증 가드 테스트
(issue #1352, #1371, #1372, #1373, #1374, #1375).

oracle A7 시그니처에서 발견된 mutation route는 인증된 master 호출자만
사용할 수 있어야 한다.
- ``PUT  /api/accounts/{id}``
- ``POST /api/accounts/{id}/suspend``
- ``POST /api/accounts/{id}/activate``
- ``PUT  /api/bots/{id}``
- ``POST /api/treasury/balance``
- ``POST /api/bots`` (#1371)
- ``DELETE /api/bots/{id}`` (#1371)
- ``POST /api/treasury/bots/{id}/allocate`` (#1372)
- ``POST /api/treasury/bots/{id}/deallocate`` (#1372)
- ``PUT  /api/config/{key}`` (#1373, scope-aware)
- ``POST /api/reports`` (#1374, scope-aware)
- ``POST /api/system/halt`` (#1375)
- ``POST /api/system/clear-halt`` (#1375)

각 라우트 × 인증 시나리오:
- Authorization 헤더 + 세션 쿠키 모두 없음 → 401
- invalid Bearer token → 401
- invalid 세션 쿠키 → 401
- ``session_service`` is None 배포 + Bearer 없음 → 401 (cookie fallback skip)
- 정상 Bearer master → 200
- 정상 ante_session master → 200 + ``request.state.member_id`` 갱신
- 인증된 non-master → 403
- master + 존재하지 않는 target → 404

401/403 응답 시 service mutation은 호출되지 않아야 한다 (early return).

#1351 ``test_member_routes_mutation_auth.py`` 패턴을 그대로 답습한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import AccountNotFoundError  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1351 패턴) ──────────────────────────────────


@dataclass
class FakeMember:
    member_id: str
    type: str = "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class FakeMemberService:
    """테스트용 MemberService stub.

    토큰 → member_id 매핑으로 ``authenticate``를 흉내낸다. ``get`` 메서드는
    ``require_master_caller`` dependency가 호출하므로 정확한 ``Member`` 형태를
    반환해야 한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add_member(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        member_type: str = "agent",
        scopes: list[str] | None = None,
        status: str = "active",
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            role=role,
            type=member_type,
            scopes=list(scopes) if scopes else [],
            status=status,
        )
        self._members[member_id] = member
        if token:
            self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)


class FakeSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self.validate_calls: list[str] = []

    def add_session(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    async def validate(self, session_id: str) -> dict | None:
        self.validate_calls.append(session_id)
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-05-09 00:00:00"}


# ── domain service fakes (account/bot/treasury) ─────────────────────────


@dataclass
class FakeAccount:
    account_id: str = "acc-target"
    name: str = "Target"
    exchange: str = "TEST"
    currency: str = "KRW"
    timezone: str = "Asia/Seoul"
    trading_hours_start: str = "09:00"
    trading_hours_end: str = "15:30"
    trading_mode: str = "VIRTUAL"
    broker_type: str = "test"
    broker_config: dict = field(default_factory=dict)
    buy_commission_rate: float = 0.0
    sell_commission_rate: float = 0.0
    market_order_reserve_buffer_rate: float = 0.0
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    credentials: dict = field(default_factory=dict)


class FakeAccountService:
    """``account_service.update / suspend / activate / get / list`` stub.

    실제 도메인 객체와 호환되는 dict-like getter를 제공한다 (timezone,
    trading_hours 같은 옵셔널 필드도 포함). 401/403 차단 시 mutation 호출이
    발생하지 않아야 함을 검증한다.
    """

    def __init__(self) -> None:
        self.update_calls: list[dict] = []
        self.suspend_calls: list[dict] = []
        self.activate_calls: list[dict] = []
        # #1375: system kill switch suspend_all / activate_all mock spy.
        self.suspend_all_calls: list[dict] = []
        self.activate_all_calls: list[dict] = []
        self._accounts: dict[str, FakeAccount] = {
            "acc-target": FakeAccount(account_id="acc-target", status="active"),
            "acc-suspended": FakeAccount(
                account_id="acc-suspended", status="suspended"
            ),
        }

    async def get(self, account_id: str) -> FakeAccount:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        return account

    async def list(self, status=None):  # noqa: A003 — domain API mirror
        return list(self._accounts.values())

    async def update(self, account_id: str, **fields) -> FakeAccount:
        self.update_calls.append({"account_id": account_id, **fields})
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        for key, value in fields.items():
            setattr(account, key, value)
        return account

    async def suspend(
        self, account_id: str, reason: str = "", suspended_by: str = ""
    ) -> None:
        self.suspend_calls.append(
            {
                "account_id": account_id,
                "reason": reason,
                "suspended_by": suspended_by,
            }
        )
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        account.status = "suspended"

    async def activate(self, account_id: str, activated_by: str = "") -> None:
        self.activate_calls.append(
            {"account_id": account_id, "activated_by": activated_by}
        )
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        account.status = "active"

    # ── #1375: system kill switch (suspend_all / activate_all) ─────────
    #
    # ``POST /api/system/halt`` / ``/clear-halt`` 핸들러는 list[dict] shape
    # (#1213) 으로 결과를 받는다 — KillSwitchAccountChange SSOT 형식.
    async def suspend_all(self, reason: str = "", suspended_by: str = "") -> list[dict]:
        self.suspend_all_calls.append({"reason": reason, "suspended_by": suspended_by})
        result: list[dict] = []
        for account in self._accounts.values():
            previous = account.status
            changed = previous == "active"
            if changed:
                account.status = "suspended"
            result.append(
                {
                    "account_id": account.account_id,
                    "previous_status": previous,
                    "status": account.status,
                    "changed": changed,
                }
            )
        return result

    async def activate_all(self, activated_by: str = "") -> list[dict]:
        self.activate_all_calls.append({"activated_by": activated_by})
        result: list[dict] = []
        for account in self._accounts.values():
            previous = account.status
            changed = previous == "suspended"
            if changed:
                account.status = "active"
            result.append(
                {
                    "account_id": account.account_id,
                    "previous_status": previous,
                    "status": account.status,
                    "changed": changed,
                }
            )
        return result


@dataclass
class _FakeBotConfig:
    bot_id: str
    account_id: str = "acc-target"
    strategy_id: str = "strat-1"
    name: str = ""
    interval_seconds: int = 60


class _FakeBotInfo(dict):
    pass


class _FakeBot:
    def __init__(self, bot_id: str, name: str = "") -> None:
        self.config = _FakeBotConfig(bot_id=bot_id, name=name or bot_id)
        self._name = name or bot_id

    def get_info(self) -> dict:
        return {
            "bot_id": self.config.bot_id,
            "name": self._name,
            "status": "stopped",
            "account_id": self.config.account_id,
            "strategy_id": self.config.strategy_id,
            "interval_seconds": self.config.interval_seconds,
        }


class FakeBotManager:
    """``bot_manager.get_bot / update_bot / create_bot / delete_bot`` stub."""

    def __init__(self) -> None:
        self.update_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self._bots: dict[str, _FakeBot] = {
            "bot-target": _FakeBot("bot-target", name="Original"),
        }

    def get_bot(self, bot_id: str):
        return self._bots.get(bot_id)

    def list_bots(self):
        return [b.get_info() for b in self._bots.values()]

    async def update_bot(self, bot_id: str, **kwargs):
        self.update_calls.append({"bot_id": bot_id, **kwargs})
        bot = self._bots.get(bot_id)
        if bot is None:
            raise ValueError(f"bot not found: {bot_id}")
        if "name" in kwargs and kwargs["name"] is not None:
            bot._name = kwargs["name"]
        return bot

    async def create_bot(self, config, strategy_cls, **kwargs):
        bot_id = getattr(config, "bot_id", "")
        self.create_calls.append({"bot_id": bot_id})
        bot = _FakeBot(bot_id, name=getattr(config, "name", "") or bot_id)
        bot.config.account_id = getattr(config, "account_id", "acc-target")
        bot.config.strategy_id = getattr(config, "strategy_id", "strat-1")
        bot.config.interval_seconds = getattr(config, "interval_seconds", 60)
        self._bots[bot_id] = bot
        return bot

    async def delete_bot(
        self, bot_id: str, handle_positions: str = "keep", hard: bool = False
    ):
        self.delete_calls.append(
            {"bot_id": bot_id, "handle_positions": handle_positions, "hard": hard}
        )
        self._bots.pop(bot_id, None)


@dataclass
class _FakeStrategyRecord:
    strategy_id: str = "strat-1"
    name: str = "test-strategy"
    version: str = "1.0.0"
    author_name: str = "tester"
    author_id: str = "tester"
    description: str = "test strategy"
    filepath: str = "/tmp/strat-1.py"


class FakeStrategyRegistry:
    """``registry.get / get_by_name`` stub."""

    def __init__(self) -> None:
        self._records: dict[str, _FakeStrategyRecord] = {
            "strat-1": _FakeStrategyRecord(strategy_id="strat-1", name="test-strategy"),
        }

    async def get(self, strategy_id: str):
        return self._records.get(strategy_id)

    async def get_by_name(self, name: str):
        return [r for r in self._records.values() if r.name == name]


@dataclass
class _FakeBudget:
    bot_id: str
    allocated: float = 0.0
    available: float = 0.0


class FakeTreasury:
    """``treasury.set_account_balance / allocate / deallocate`` stub."""

    def __init__(self) -> None:
        self.set_balance_calls: list[float] = []
        self.allocate_calls: list[dict] = []
        self.deallocate_calls: list[dict] = []
        self._balance: float = 10_000_000.0
        self._unallocated: float = 10_000_000.0
        self._budgets: dict[str, _FakeBudget] = {}
        self.account_id = "acc-target"
        self.currency = "KRW"

    @property
    def account_balance(self) -> float:
        return self._balance

    async def set_account_balance(self, balance: float) -> None:
        self.set_balance_calls.append(balance)
        self._balance = balance

    async def allocate(self, bot_id: str, amount: float) -> bool:
        self.allocate_calls.append({"bot_id": bot_id, "amount": amount})
        if amount <= 0 or self._unallocated < amount:
            return False
        budget = self._budgets.setdefault(bot_id, _FakeBudget(bot_id=bot_id))
        budget.allocated += amount
        budget.available += amount
        self._unallocated -= amount
        return True

    async def deallocate(self, bot_id: str, amount: float) -> bool:
        self.deallocate_calls.append({"bot_id": bot_id, "amount": amount})
        budget = self._budgets.get(bot_id)
        if budget is None or amount <= 0 or budget.available < amount:
            return False
        budget.allocated -= amount
        budget.available -= amount
        self._unallocated += amount
        return True

    def get_summary(self) -> dict:
        return {"account_balance": self._balance, "total_balance": self._balance}

    def get_budget(self, bot_id: str):
        return self._budgets.get(bot_id)

    def list_budgets(self):
        return list(self._budgets.values())


class FakeReportStore:
    """``report_store.submit`` stub (#1374).

    401/403 차단 시 ``submit`` 이 호출되지 않음을 ``submit_calls`` mock spy
    로 검증한다. 200 경로에서는 ``StrategyReport`` 인자를 그대로 보관해
    ``submitted_by`` 가 caller_id 로 설정되었는지 확인한다.
    """

    def __init__(self) -> None:
        self.submit_calls: list[Any] = []

    async def submit(self, report: Any) -> None:
        self.submit_calls.append(report)


class FakeDynamicConfig:
    """``config_service.exists / get / set / get_all`` stub (#1373).

    ``test_system_config_api.FakeDynamicConfig`` 패턴을 답습. 401/403 차단 시
    ``set`` 이 호출되지 않음을 ``set_calls`` mock spy 로 검증한다.
    """

    def __init__(self) -> None:
        self.set_calls: list[dict] = []
        self._configs: dict[str, dict] = {
            "system.log_level": {"value": "INFO", "category": "system"},
            "risk.max_mdd": {"value": 0.1, "category": "risk"},
        }

    async def exists(self, key: str) -> bool:
        return key in self._configs

    async def get(self, key: str, default: object = None) -> object:
        if key in self._configs:
            return self._configs[key]["value"]
        return default

    async def get_all(self) -> list[dict]:
        return [
            {
                "key": key,
                "value": item["value"],
                "category": item["category"],
                "updated_at": "2026-05-10T00:00:00",
            }
            for key, item in self._configs.items()
        ]

    async def set(
        self,
        key: str,
        value: object,
        category: str = "",
        changed_by: str = "",
    ) -> None:
        self.set_calls.append(
            {
                "key": key,
                "value": value,
                "category": category,
                "changed_by": changed_by,
            }
        )
        self._configs[key] = {"value": value, "category": category}


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    # master(human, role=master) — 모든 mutation 통과.
    svc.add_member(
        "master-user", token="master-token", role="master", member_type="human"
    )
    # agent default (no scopes) — config:write 미보유 agent. 403 검증용.
    svc.add_member("agent-01", token="agent-token", role="default")
    # human admin/default — scope 무관 통과 검증용 (#1373).
    svc.add_member(
        "human-admin",
        token="human-token",
        role="default",
        member_type="human",
    )
    # agent + config:write scope — agent 정상 경로 검증용 (#1373).
    svc.add_member(
        "agent-config",
        token="agent-config-token",
        role="default",
        member_type="agent",
        scopes=["config:write"],
    )
    # agent + report:write scope — agent 정상 경로 검증용 (#1374).
    svc.add_member(
        "agent-report",
        token="agent-report-token",
        role="default",
        member_type="agent",
        scopes=["report:write"],
    )
    # inactive 멤버 — suspended/revoked 세션 fallback 차단 검증용 (#1373).
    svc.add_member(
        "inactive-member",
        token="inactive-token",
        role="default",
        member_type="human",
        status="suspended",
    )
    return svc


@pytest.fixture
def session_service() -> FakeSessionService:
    svc = FakeSessionService()
    svc.add_session("master-session-id", member_id="master-user")
    svc.add_session("agent-session-id", member_id="agent-01")
    svc.add_session("human-session-id", member_id="human-admin")
    svc.add_session("agent-config-session-id", member_id="agent-config")
    svc.add_session("agent-report-session-id", member_id="agent-report")
    svc.add_session("inactive-session-id", member_id="inactive-member")
    return svc


@pytest.fixture
def account_service() -> FakeAccountService:
    return FakeAccountService()


@pytest.fixture
def bot_manager() -> FakeBotManager:
    return FakeBotManager()


@pytest.fixture
def treasury() -> FakeTreasury:
    return FakeTreasury()


@pytest.fixture
def strategy_registry() -> FakeStrategyRegistry:
    return FakeStrategyRegistry()


@pytest.fixture
def dynamic_config() -> FakeDynamicConfig:
    return FakeDynamicConfig()


@pytest.fixture
def report_store() -> FakeReportStore:
    return FakeReportStore()


@pytest.fixture
def _mock_strategy_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """``StrategyLoader.load`` 모킹 — 테스트 파일 시스템 의존성 제거."""

    class _FakeStrategy:
        pass

    monkeypatch.setattr(
        "ante.strategy.loader.StrategyLoader.load",
        staticmethod(lambda path: _FakeStrategy),
    )


@pytest.fixture
def client(
    member_service: FakeMemberService,
    session_service: FakeSessionService,
    account_service: FakeAccountService,
    bot_manager: FakeBotManager,
    treasury: FakeTreasury,
    strategy_registry: FakeStrategyRegistry,
    dynamic_config: FakeDynamicConfig,
    report_store: FakeReportStore,
) -> TestClient:
    app = create_app(
        member_service=member_service,
        session_service=session_service,
        account_service=account_service,
        bot_manager=bot_manager,
        treasury=treasury,
        strategy_registry=strategy_registry,
        dynamic_config=dynamic_config,
        report_store=report_store,
    )
    return TestClient(app)


@pytest.fixture
def client_no_session_service(
    member_service: FakeMemberService,
    account_service: FakeAccountService,
    bot_manager: FakeBotManager,
    treasury: FakeTreasury,
    strategy_registry: FakeStrategyRegistry,
    dynamic_config: FakeDynamicConfig,
    report_store: FakeReportStore,
) -> TestClient:
    """``session_service is None`` 배포 분기 시뮬레이션."""
    app = create_app(
        member_service=member_service,
        account_service=account_service,
        bot_manager=bot_manager,
        treasury=treasury,
        strategy_registry=strategy_registry,
        dynamic_config=dynamic_config,
        report_store=report_store,
    )
    return TestClient(app)


# ── 라우트별 호출 헬퍼 ──────────────────────────────────────────────────


def _account_update(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.put(
        "/api/accounts/acc-target",
        json=payload if payload is not None else {"name": "Renamed"},
        headers=headers or {},
    )


def _account_suspend(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.post(
        "/api/accounts/acc-target/suspend",
        json=payload if payload is not None else {"reason": "test"},
        headers=headers or {},
    )


def _account_activate(client: TestClient, headers: dict | None = None, **_):
    return client.post(
        "/api/accounts/acc-suspended/activate",
        headers=headers or {},
    )


def _bot_update(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.put(
        "/api/bots/bot-target",
        json=payload if payload is not None else {"name": "Renamed Bot"},
        headers=headers or {},
    )


def _treasury_set_balance(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.post(
        "/api/treasury/balance",
        json=payload if payload is not None else {"balance": 12345.0},
        headers=headers or {},
    )


def _treasury_allocate(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.post(
        "/api/treasury/bots/bot-target/allocate",
        json=payload if payload is not None else {"amount": 1000.0},
        headers=headers or {},
    )


def _treasury_deallocate(
    client: TestClient, headers: dict | None = None, payload: dict | None = None
):
    return client.post(
        "/api/treasury/bots/bot-target/deallocate",
        json=payload if payload is not None else {"amount": 1000.0},
        headers=headers or {},
    )


MUTATION_ROUTES = [
    ("account_update", _account_update, "account_service", "update_calls"),
    ("account_suspend", _account_suspend, "account_service", "suspend_calls"),
    ("account_activate", _account_activate, "account_service", "activate_calls"),
    ("bot_update", _bot_update, "bot_manager", "update_calls"),
    ("treasury_set_balance", _treasury_set_balance, "treasury", "set_balance_calls"),
    # #1372: treasury budget mutation 인증 가드 추가.
    ("treasury_allocate", _treasury_allocate, "treasury", "allocate_calls"),
    ("treasury_deallocate", _treasury_deallocate, "treasury", "deallocate_calls"),
]


def _service_calls(fixtures: dict, service_attr: str, calls_attr: str) -> list:
    svc = fixtures[service_attr]
    return getattr(svc, calls_attr)


# ── 401: 인증 자체가 없는 케이스 ──────────────────────────────────────


class TestNoAuth401:
    """Authorization 헤더 + 세션 쿠키 모두 없음 → 401."""

    @pytest.mark.parametrize(
        "name,call,service_attr,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_without_any_auth(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        bot_manager: FakeBotManager,
        treasury: FakeTreasury,
        name: str,
        call,
        service_attr: str,
        calls_attr: str,
    ) -> None:
        resp = call(client)
        assert resp.status_code == 401, (
            f"{name}: 인증 없는 호출이 401이 아님 ({resp.status_code}: {resp.text})"
        )
        fixtures = {
            "account_service": account_service,
            "bot_manager": bot_manager,
            "treasury": treasury,
        }
        assert _service_calls(fixtures, service_attr, calls_attr) == [], (
            f"{name}: 401 차단 시 service mutation이 호출되어선 안 된다"
        )


class TestInvalidBearerToken401:
    """invalid Bearer token → 401, mutation 미호출."""

    @pytest.mark.parametrize(
        "name,call,service_attr,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_with_invalid_bearer(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        bot_manager: FakeBotManager,
        treasury: FakeTreasury,
        name: str,
        call,
        service_attr: str,
        calls_attr: str,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer invalid-token"})
        assert resp.status_code == 401, (
            f"{name}: invalid Bearer가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        fixtures = {
            "account_service": account_service,
            "bot_manager": bot_manager,
            "treasury": treasury,
        }
        assert _service_calls(fixtures, service_attr, calls_attr) == []


class TestInvalidSessionCookie401:
    """등록되지 않은 ``ante_session`` 쿠키 → 401."""

    @pytest.mark.parametrize(
        "name,call,service_attr,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_with_invalid_session_cookie(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        bot_manager: FakeBotManager,
        treasury: FakeTreasury,
        session_service: FakeSessionService,
        name: str,
        call,
        service_attr: str,
        calls_attr: str,
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = call(client)
        assert resp.status_code == 401, (
            f"{name}: invalid 세션 쿠키가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        fixtures = {
            "account_service": account_service,
            "bot_manager": bot_manager,
            "treasury": treasury,
        }
        assert _service_calls(fixtures, service_attr, calls_attr) == []
        assert "unknown-session-id" in session_service.validate_calls
        client.cookies.delete("ante_session")


class TestSessionServiceNoneFallbackSkip:
    """``session_service is None`` 배포 분기 + Bearer 없음 → 401."""

    @pytest.mark.parametrize(
        "name,call,service_attr,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_when_session_service_none_and_no_bearer(
        self,
        client_no_session_service: TestClient,
        account_service: FakeAccountService,
        bot_manager: FakeBotManager,
        treasury: FakeTreasury,
        name: str,
        call,
        service_attr: str,
        calls_attr: str,
    ) -> None:
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = call(client_no_session_service)
        assert resp.status_code == 401, (
            f"{name}: session_service None + 쿠키만 있으면 401이어야 함 "
            f"({resp.status_code}: {resp.text})"
        )
        fixtures = {
            "account_service": account_service,
            "bot_manager": bot_manager,
            "treasury": treasury,
        }
        assert _service_calls(fixtures, service_attr, calls_attr) == []
        client_no_session_service.cookies.delete("ante_session")


# ── 200: 정상 인증 케이스 ───────────────────────────────────────────────


class TestBearerMasterSuccess:
    """master Bearer 토큰 → 200, audit subject = master-user."""

    def test_account_update_with_master_bearer_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.put(
            "/api/accounts/acc-target",
            json={"name": "Renamed"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["account"]["name"] == "Renamed"
        assert account_service.update_calls[-1]["account_id"] == "acc-target"

    def test_account_suspend_with_master_bearer_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "test"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_account_activate_with_master_bearer_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            "/api/accounts/acc-suspended/activate",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.activate_calls[-1]["activated_by"] == "master-user"

    def test_bot_update_with_master_bearer_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target",
            json={"name": "Renamed Bot"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert bot_manager.update_calls[-1]["bot_id"] == "bot-target"
        assert bot_manager.update_calls[-1].get("name") == "Renamed Bot"

    def test_treasury_set_balance_with_master_bearer_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/balance",
            json={"balance": 50000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert treasury.set_balance_calls == [50000.0]

    def test_treasury_allocate_with_master_bearer_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": 1000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert treasury.allocate_calls[-1]["bot_id"] == "bot-target"
        assert treasury.allocate_calls[-1]["amount"] == 1000.0

    def test_treasury_deallocate_with_master_bearer_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        # 먼저 예산 할당 (deallocate 가능 상태 만들기).
        client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": 5000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json={"amount": 1000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert treasury.deallocate_calls[-1]["bot_id"] == "bot-target"
        assert treasury.deallocate_calls[-1]["amount"] == 1000.0


class TestSessionCookieMasterSuccess:
    """master ``ante_session`` 쿠키 → 200 + ``request.state.member_id`` 갱신.

    audit subject가 caller_id(=master-user)로 기록되는지 검증한다.
    """

    def test_account_suspend_with_master_session_cookie_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "via cookie"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_account_activate_with_master_session_cookie_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/accounts/acc-suspended/activate")
        assert resp.status_code == 200, resp.text
        assert account_service.activate_calls[-1]["activated_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_bot_update_with_master_session_cookie_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.put("/api/bots/bot-target", json={"name": "C"})
        assert resp.status_code == 200, resp.text
        assert bot_manager.update_calls[-1]["bot_id"] == "bot-target"
        client.cookies.delete("ante_session")

    def test_treasury_set_balance_with_master_session_cookie_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/treasury/balance", json={"balance": 100.0})
        assert resp.status_code == 200, resp.text
        assert treasury.set_balance_calls == [100.0]
        client.cookies.delete("ante_session")

    def test_treasury_allocate_with_master_session_cookie_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": 2000.0},
        )
        assert resp.status_code == 200, resp.text
        assert treasury.allocate_calls[-1]["bot_id"] == "bot-target"
        assert treasury.allocate_calls[-1]["amount"] == 2000.0
        client.cookies.delete("ante_session")

    def test_treasury_deallocate_with_master_session_cookie_succeeds(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        # 먼저 예산 할당.
        client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": 5000.0},
        )
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json={"amount": 1500.0},
        )
        assert resp.status_code == 200, resp.text
        assert treasury.deallocate_calls[-1]["bot_id"] == "bot-target"
        assert treasury.deallocate_calls[-1]["amount"] == 1500.0
        client.cookies.delete("ante_session")


# ── 403: 인증된 non-master ─────────────────────────────────────────────


class TestNonMaster403:
    """인증된 non-master → 403, mutation 미호출."""

    @pytest.mark.parametrize(
        "name,call,service_attr,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_non_master_bearer_returns_403(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        bot_manager: FakeBotManager,
        treasury: FakeTreasury,
        name: str,
        call,
        service_attr: str,
        calls_attr: str,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer agent-token"})
        assert resp.status_code == 403, (
            f"{name}: non-master Bearer가 403이 아님 ({resp.status_code}: {resp.text})"
        )
        fixtures = {
            "account_service": account_service,
            "bot_manager": bot_manager,
            "treasury": treasury,
        }
        assert _service_calls(fixtures, service_attr, calls_attr) == [], (
            f"{name}: 403 차단 시 service mutation이 호출되어선 안 된다"
        )


# ── 404: master + missing target ───────────────────────────────────────


class TestMasterMissingTarget404:
    """master 인증 통과 + 존재하지 않는 target → 404."""

    def test_account_update_missing_returns_404(self, client: TestClient) -> None:
        resp = client.put(
            "/api/accounts/no-such-account",
            json={"name": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_account_suspend_missing_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/accounts/no-such-account/suspend",
            json={"reason": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_account_activate_missing_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/accounts/no-such-account/activate",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_bot_update_missing_returns_404(self, client: TestClient) -> None:
        resp = client.put(
            "/api/bots/no-such-bot",
            json={"name": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_treasury_allocate_missing_bot_returns_404(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        """master 인증 + 존재하지 않는 봇 → 404, allocate 미호출."""
        resp = client.post(
            "/api/treasury/bots/no-such-bot/allocate",
            json={"amount": 1000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert treasury.allocate_calls == []

    def test_treasury_deallocate_missing_bot_returns_404(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        """master 인증 + 존재하지 않는 봇 → 404, deallocate 미호출."""
        resp = client.post(
            "/api/treasury/bots/no-such-bot/deallocate",
            json={"amount": 1000.0},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert treasury.deallocate_calls == []


# ── raw body 패턴: 401 우선 ────────────────────────────────────────────


class TestUpdateBotAuthFirstOverBodyValidation:
    """``update_bot``은 ``update_scopes``와 동일하게 인증 가드가 body
    validation보다 먼저 실행되어야 한다 (#1352).

    Authorization 없음 + body invalid → 401 (NOT 422).
    """

    def test_update_bot_unauth_invalid_body_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target", json={"interval_seconds": "not-a-number"}
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert bot_manager.update_calls == []

    def test_update_bot_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target",
            json={"interval_seconds": "x"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert bot_manager.update_calls == []

    def test_update_bot_master_invalid_body_returns_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """인증 통과 + body invalid → 422 (정상 검증 경로)."""
        resp = client.put(
            "/api/bots/bot-target",
            json={"interval_seconds": "not-a-number"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert bot_manager.update_calls == []

    def test_update_bot_master_empty_body_returns_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert bot_manager.update_calls == []

    def test_update_bot_master_non_json_body_returns_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target",
            content=b"not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert bot_manager.update_calls == []


class TestSuspendAccountAuthFirstOverBodyValidation:
    """``suspend_account``도 raw body 패턴 + 401 우선이어야 한다 (#1352 2차 fix).

    이전에는 ``body: AccountSuspendRequest | None = None`` typed 인자를 사용해
    FastAPI가 dependency 해결 전에 JSON body를 파싱했고, 그 결과 malformed body
    + unauth 케이스에서 422가 401/403보다 먼저 반환되어 ``update_bot``/
    ``set_balance``/``update_scopes``의 auth-first 계약과 어긋났다.
    """

    def test_suspend_unauth_malformed_json_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """Authorization 없음 + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body 파싱보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert account_service.suspend_calls == []

    def test_suspend_unauth_non_object_json_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """Authorization 없음 + JSON이 object가 아님 → 401 (NOT 422)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json=["not", "an", "object"],
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert account_service.suspend_calls == []

    def test_suspend_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """invalid Bearer + invalid body → 401 (NOT 422)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": 123},  # reason은 str여야 함
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert account_service.suspend_calls == []

    def test_suspend_master_empty_body_returns_200_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + 빈 body → 200, default reason (``dashboard``)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            content=b"",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["reason"] == "dashboard"
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_suspend_master_null_body_returns_200_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + JSON ``null`` → 200, default reason (#1352 3차 fix).

        이전 ``body: AccountSuspendRequest | None = Body(None)`` 계약에서는
        ``null`` body 가 ``body is None`` 과 동등하게 default reason 으로
        흘러갔다. raw body 패턴 도입 후에도 이 호환성을 유지해야 한다.
        """
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            content=b"null",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["reason"] == "dashboard"
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_suspend_master_empty_object_body_returns_200_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + ``{}`` → 200, default reason."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["reason"] == "dashboard"
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_suspend_master_with_reason_returns_200_and_propagates_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + ``{"reason": "X"}`` → 200, reason 그대로 전달."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "manual override"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_calls[-1]["reason"] == "manual override"
        assert account_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_suspend_master_reason_with_extra_key_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + reason + extra key → 422 (``extra="forbid"`` 유지)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "X", "extra": "Y"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_calls == []

    def test_suspend_master_malformed_json_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + malformed JSON → 422 (정상 검증 경로)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            content=b"{not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert account_service.suspend_calls == []

    def test_suspend_master_non_object_json_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + JSON이 object가 아님 → 422."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_calls == []

    def test_suspend_master_extra_key_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + extra key → 422 (``extra="forbid"`` 정합)."""
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "x", "unexpected": True},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_calls == []


class TestSetBalanceAuthFirstOverBodyValidation:
    """``set_balance``도 raw body 패턴 + 401 우선이어야 한다."""

    def test_set_balance_unauth_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post("/api/treasury/balance", json={"balance": "not-a-number"})
        assert resp.status_code == 401
        assert treasury.set_balance_calls == []

    def test_set_balance_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/balance",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert treasury.set_balance_calls == []

    def test_set_balance_master_invalid_body_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/balance",
            json={"balance": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.set_balance_calls == []


class TestAllocateAuthFirstOverBodyValidation:
    """``allocate`` 도 raw body 패턴 + 401 우선이어야 한다 (#1372).

    Authorization 없음 + body invalid → 401 (NOT 422). master 인증 통과 후
    invalid body 만 422 로 떨어진다.
    """

    def test_allocate_unauth_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": "not-a-number"},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert treasury.allocate_calls == []

    def test_allocate_unauth_malformed_json_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert treasury.allocate_calls == []

    def test_allocate_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert treasury.allocate_calls == []

    def test_allocate_master_invalid_body_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json={"amount": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.allocate_calls == []

    def test_allocate_master_empty_body_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert treasury.allocate_calls == []

    def test_allocate_master_non_object_json_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/allocate",
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.allocate_calls == []


class TestDeallocateAuthFirstOverBodyValidation:
    """``deallocate`` 도 raw body 패턴 + 401 우선이어야 한다 (#1372).

    ``allocate`` 와 동일 매트릭스. 401/403 시 ``treasury.deallocate`` 미호출.
    """

    def test_deallocate_unauth_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json={"amount": "not-a-number"},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert treasury.deallocate_calls == []

    def test_deallocate_unauth_malformed_json_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert treasury.deallocate_calls == []

    def test_deallocate_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert treasury.deallocate_calls == []

    def test_deallocate_master_invalid_body_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json={"amount": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.deallocate_calls == []

    def test_deallocate_master_empty_body_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert treasury.deallocate_calls == []

    def test_deallocate_master_non_object_json_returns_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/bots/bot-target/deallocate",
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.deallocate_calls == []


# ── extra="forbid" 회귀 ────────────────────────────────────────────────


class TestExtraForbid:
    """``BotUpdateRequest`` / ``BalanceSetRequest`` / ``AccountSuspendRequest``는
    ``extra="forbid"``를 강제한다.

    OpenAPI ``additionalProperties: false``와 런타임 검증 동작을 일치시킨다
    (#1351 2차 review 회귀 예방 패턴).
    """

    def test_update_bot_rejects_unknown_field_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.put(
            "/api/bots/bot-target",
            json={"name": "x", "unexpected": True},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert bot_manager.update_calls == []

    def test_set_balance_rejects_unknown_field_with_422(
        self, client: TestClient, treasury: FakeTreasury
    ) -> None:
        resp = client.post(
            "/api/treasury/balance",
            json={"balance": 100.0, "unexpected": True},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert treasury.set_balance_calls == []

    def test_suspend_rejects_unknown_field_with_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            "/api/accounts/acc-target/suspend",
            json={"reason": "x", "unexpected": True},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_calls == []


# ── OpenAPI 응답 401/403 회귀 ──────────────────────────────────────────


class TestOpenAPIResponses401403:
    """mutation route의 OpenAPI ``responses``에 401/403 항목이 있어야 한다.

    ``frontend/openapi.json`` codegen 산출물이 401/403 분기를 인식할 수 있도록
    contract에 명시해야 한다(#1352 / #1371 risk: contract-drift).
    """

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/accounts/{account_id}", "put"),
            ("/api/accounts/{account_id}/suspend", "post"),
            ("/api/accounts/{account_id}/activate", "post"),
            ("/api/bots/{bot_id}", "put"),
            ("/api/treasury/balance", "post"),
            # #1371: 봇 lifecycle (create / delete) 인증 가드 추가.
            ("/api/bots", "post"),
            ("/api/bots/{bot_id}", "delete"),
            # #1372: treasury budget mutation 인증 가드 추가.
            ("/api/treasury/bots/{bot_id}/allocate", "post"),
            ("/api/treasury/bots/{bot_id}/deallocate", "post"),
            # #1373: dynamic config update 인증 가드 추가.
            ("/api/config/{key}", "put"),
            # #1374: report submit 인증 가드 추가.
            ("/api/reports", "post"),
            # #1375: system kill switch 인증 가드 추가.
            ("/api/system/halt", "post"),
            ("/api/system/clear-halt", "post"),
        ],
    )
    def test_openapi_lists_401_response(self, path: str, method: str) -> None:
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"][path][method]
        responses = operation.get("responses", {})
        assert "401" in responses, (
            f"{method.upper()} {path} 응답에 401 항목이 없음: "
            f"{sorted(responses.keys())}"
        )

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/accounts/{account_id}", "put"),
            ("/api/accounts/{account_id}/suspend", "post"),
            ("/api/accounts/{account_id}/activate", "post"),
            ("/api/bots/{bot_id}", "put"),
            ("/api/treasury/balance", "post"),
            # #1371: 봇 lifecycle (create / delete) 인증 가드 추가.
            ("/api/bots", "post"),
            ("/api/bots/{bot_id}", "delete"),
            # #1372: treasury budget mutation 인증 가드 추가.
            ("/api/treasury/bots/{bot_id}/allocate", "post"),
            ("/api/treasury/bots/{bot_id}/deallocate", "post"),
            # #1373: dynamic config update 인증 가드 추가.
            ("/api/config/{key}", "put"),
            # #1374: report submit 인증 가드 추가.
            ("/api/reports", "post"),
            # #1375: system kill switch 인증 가드 추가.
            ("/api/system/halt", "post"),
            ("/api/system/clear-halt", "post"),
        ],
    )
    def test_openapi_lists_403_response(self, path: str, method: str) -> None:
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"][path][method]
        responses = operation.get("responses", {})
        assert "403" in responses, (
            f"{method.upper()} {path} 응답에 403 항목이 없음: "
            f"{sorted(responses.keys())}"
        )

    @pytest.mark.parametrize(
        "schema_name",
        [
            "BotCreateRequest",
            "BotUpdateRequest",
            "BalanceSetRequest",
            # #1372: BudgetChangeRequest 도 raw body 패턴으로 전환 후 명시 등록.
            "BudgetChangeRequest",
            # #1373: ConfigUpdateRequest 도 raw body 패턴으로 전환 후 명시 등록.
            "ConfigUpdateRequest",
            # #1374: ReportSubmitRequest 도 raw body 패턴으로 전환 후 명시 등록.
            "ReportSubmitRequest",
            # #1375: HaltRequest / ClearHaltRequest 도 raw body 패턴으로
            # 전환 후 명시 등록.
            "HaltRequest",
            "ClearHaltRequest",
        ],
    )
    def test_openapi_components_schemas_registered(self, schema_name: str) -> None:
        """``BotCreateRequest`` / ``BotUpdateRequest`` / ``BalanceSetRequest``는
        raw body 패턴 적용으로 FastAPI 자동 등록 경로를 거치지 않으므로,
        ``_install_openapi_customizer``가 ``components.schemas``에 명시 등록해야
        frontend codegen이 ``export type``을 만들 수 있다.
        """
        app = create_app()
        schema = app.openapi()
        components = schema.get("components", {}).get("schemas", {})
        assert schema_name in components, (
            f"components.schemas에 {schema_name}가 등록되어 있지 않음: "
            f"{sorted(components.keys())[:30]}..."
        )


# ── #1371: POST /api/bots / DELETE /api/bots/{id} 인증 매트릭스 ─────────


_VALID_CREATE_PAYLOAD: dict = {
    "bot_id": "bot-new",
    "strategy_name": "test-strategy",
    "account_id": "acc-target",
    "interval_seconds": 60,
}


class TestCreateBotAuthMatrix:
    """``POST /api/bots`` 는 ``update_bot`` (#1352) 와 동일한 raw-body 패턴 +
    auth-first 계약을 따른다 (#1371). 인증 가드가 body 파싱보다 먼저 실행되어야
    한다.

    401/403 시 ``bot_manager.create_bot`` 이 호출되지 않음을 mock spy
    (``create_calls``) 로 검증한다.
    """

    # 401 — 인증 자체가 없음 ─────────────────────────────────────────

    def test_create_bot_unauth_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post("/api/bots", json=_VALID_CREATE_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert bot_manager.create_calls == []

    def test_create_bot_invalid_bearer_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            json=_VALID_CREATE_PAYLOAD,
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert bot_manager.create_calls == []

    def test_create_bot_invalid_session_cookie_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.post("/api/bots", json=_VALID_CREATE_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert bot_manager.create_calls == []
        client.cookies.delete("ante_session")

    def test_create_bot_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        bot_manager: FakeBotManager,
        _mock_strategy_loader,
    ) -> None:
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.post("/api/bots", json=_VALID_CREATE_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert bot_manager.create_calls == []
        client_no_session_service.cookies.delete("ante_session")

    # auth-first: bad body 라도 401 우선 ─────────────────────────────

    def test_create_bot_unauth_invalid_body_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        """unauth + body invalid → 401 (NOT 422). update_bot 패턴 답습."""
        resp = client.post(
            "/api/bots",
            json={"bot_id": "bot-x", "interval_seconds": "not-a-number"},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert bot_manager.create_calls == []

    def test_create_bot_unauth_malformed_json_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            "/api/bots",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert bot_manager.create_calls == []

    # 200 (실제 POST는 201) — master 인증 통과 ─────────────────────────

    def test_create_bot_master_bearer_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            json=_VALID_CREATE_PAYLOAD,
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 201, resp.text
        assert bot_manager.create_calls[-1]["bot_id"] == "bot-new"

    def test_create_bot_master_session_cookie_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/bots", json=_VALID_CREATE_PAYLOAD)
        assert resp.status_code == 201, resp.text
        assert bot_manager.create_calls[-1]["bot_id"] == "bot-new"
        client.cookies.delete("ante_session")

    # 422 — 인증 통과 + body invalid → 정상 검증 경로 ─────────────────

    def test_create_bot_master_invalid_body_returns_422(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            json={"bot_id": "bot-y", "interval_seconds": "not-a-number"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert bot_manager.create_calls == []

    def test_create_bot_master_empty_body_returns_422(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert bot_manager.create_calls == []

    # 403 — 인증된 non-master ────────────────────────────────────────

    def test_create_bot_non_master_bearer_returns_403(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            json=_VALID_CREATE_PAYLOAD,
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert bot_manager.create_calls == []

    # 404 — master + missing strategy / account ─────────────────────

    def test_create_bot_master_strategy_not_found_returns_404(
        self, client: TestClient, bot_manager: FakeBotManager, _mock_strategy_loader
    ) -> None:
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-z",
                "strategy_name": "no-such-strategy",
                "account_id": "acc-target",
            },
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert bot_manager.create_calls == []

    def test_create_bot_master_account_not_found_returns_404(
        self,
        client: TestClient,
        bot_manager: FakeBotManager,
        account_service: FakeAccountService,
        _mock_strategy_loader,
    ) -> None:
        """master 인증 통과 + 존재하지 않는 account_id → 404 (AccountNotFoundError).

        ``AccountNotFoundError``는 web layer에서 404로 변환된다 (account 라우트
        SSOT와 동일). 봇은 생성되지 않아야 한다.
        """
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-q",
                "strategy_name": "test-strategy",
                "account_id": "no-such-account",
            },
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert bot_manager.create_calls == []


class TestDeleteBotAuthMatrix:
    """``DELETE /api/bots/{id}`` 인증 가드 매트릭스 (#1371). body 가 없으므로
    raw-body cold-path는 적용되지 않지만 인증 → 404 → mutation 순서를 따른다.

    401/403 시 ``bot_manager.delete_bot`` 이 호출되지 않음을 mock spy
    (``delete_calls``) 로 검증한다.
    """

    def test_delete_bot_unauth_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.delete("/api/bots/bot-target")
        assert resp.status_code == 401, resp.text
        assert bot_manager.delete_calls == []

    def test_delete_bot_invalid_bearer_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.delete(
            "/api/bots/bot-target",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert bot_manager.delete_calls == []

    def test_delete_bot_invalid_session_cookie_returns_401(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.delete("/api/bots/bot-target")
        assert resp.status_code == 401, resp.text
        assert bot_manager.delete_calls == []
        client.cookies.delete("ante_session")

    def test_delete_bot_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        bot_manager: FakeBotManager,
    ) -> None:
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.delete("/api/bots/bot-target")
        assert resp.status_code == 401, resp.text
        assert bot_manager.delete_calls == []
        client_no_session_service.cookies.delete("ante_session")

    def test_delete_bot_master_bearer_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.delete(
            "/api/bots/bot-target",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 204, resp.text
        assert bot_manager.delete_calls[-1]["bot_id"] == "bot-target"
        assert bot_manager.delete_calls[-1]["handle_positions"] == "keep"

    def test_delete_bot_master_session_cookie_succeeds(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.delete("/api/bots/bot-target")
        assert resp.status_code == 204, resp.text
        assert bot_manager.delete_calls[-1]["bot_id"] == "bot-target"
        client.cookies.delete("ante_session")

    def test_delete_bot_non_master_bearer_returns_403(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.delete(
            "/api/bots/bot-target",
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert bot_manager.delete_calls == []

    def test_delete_bot_master_missing_returns_404(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        resp = client.delete(
            "/api/bots/no-such-bot",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert bot_manager.delete_calls == []


# ── #1373: PUT /api/config/{key} scope-aware 인증 매트릭스 ───────────────


_VALID_CONFIG_PAYLOAD: dict = {"value": "DEBUG"}
_CONFIG_KEY = "system.log_level"
_CONFIG_PATH = f"/api/config/{_CONFIG_KEY}"


class TestUpdateConfigAuthMatrix:
    """``PUT /api/config/{key}`` 는 scope-aware 인증 가드를 따른다 (#1373).

    spec ``docs/specs/member/02-design-decisions.md:210-221`` 의
    ``require_scope`` predicate 와 정합:
    - master role → 통과
    - human type → 통과 (scope 무관)
    - agent + ``config:write`` ∈ scopes → 통과
    - 그 외 → 403

    raw body 패턴 + auth-first: 인증 가드가 body validation 보다 먼저 실행되어
    unauth + bad-body 시 401 우선. 401/403 시 ``config_service.set`` 미호출
    (mock spy 검증).
    """

    # 401 — 인증 자체가 없음 ─────────────────────────────────────────

    def test_update_config_unauth_returns_401(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        resp = client.put(_CONFIG_PATH, json=_VALID_CONFIG_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert dynamic_config.set_calls == []

    def test_update_config_invalid_bearer_returns_401(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        resp = client.put(
            _CONFIG_PATH,
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert dynamic_config.set_calls == []

    def test_update_config_invalid_session_cookie_returns_401(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.put(_CONFIG_PATH, json=_VALID_CONFIG_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert dynamic_config.set_calls == []
        client.cookies.delete("ante_session")

    def test_update_config_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """``session_service is None`` 배포 + 쿠키만 → 401 (cookie fallback skip)."""
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.put(_CONFIG_PATH, json=_VALID_CONFIG_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert dynamic_config.set_calls == []
        client_no_session_service.cookies.delete("ante_session")

    # auth-first: bad body 라도 401 우선 ─────────────────────────────

    def test_update_config_unauth_invalid_body_returns_401(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """unauth + body invalid → 401 (NOT 422). update_bot 패턴 답습."""
        resp = client.put(_CONFIG_PATH, json=["not", "an", "object"])
        assert resp.status_code == 401, (
            f"인증 가드가 body validation 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert dynamic_config.set_calls == []

    def test_update_config_unauth_malformed_json_returns_401(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.put(
            _CONFIG_PATH,
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert dynamic_config.set_calls == []

    # 200 — master 인증 통과 ─────────────────────────────────────────

    def test_update_config_master_bearer_succeeds(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        resp = client.put(
            _CONFIG_PATH,
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["key"] == _CONFIG_KEY
        assert body["new_value"] == "DEBUG"
        assert len(dynamic_config.set_calls) == 1
        assert dynamic_config.set_calls[-1]["changed_by"] == "master-user"

    def test_update_config_master_session_cookie_succeeds(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.put(_CONFIG_PATH, json=_VALID_CONFIG_PAYLOAD)
        assert resp.status_code == 200, resp.text
        assert dynamic_config.set_calls[-1]["changed_by"] == "master-user"
        client.cookies.delete("ante_session")

    # 200 — human (scope 무관) 통과 ──────────────────────────────────

    def test_update_config_human_bearer_succeeds(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """spec predicate: human 멤버는 scope 검증을 무조건 통과한다."""
        resp = client.put(
            _CONFIG_PATH,
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer human-token"},
        )
        assert resp.status_code == 200, resp.text
        assert dynamic_config.set_calls[-1]["changed_by"] == "human-admin"

    # 200 — agent + config:write scope ───────────────────────────────

    def test_update_config_agent_with_config_write_succeeds(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """agent + ``config:write`` ∈ scopes → 통과 (spec predicate 정합)."""
        resp = client.put(
            _CONFIG_PATH,
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer agent-config-token"},
        )
        assert resp.status_code == 200, resp.text
        assert dynamic_config.set_calls[-1]["changed_by"] == "agent-config"

    # 403 — agent without scope ──────────────────────────────────────

    def test_update_config_agent_without_config_write_returns_403(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """agent + scope 미보유 → 403 (spec predicate 정합)."""
        resp = client.put(
            _CONFIG_PATH,
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert dynamic_config.set_calls == []

    # 403 — inactive 멤버 (suspended/revoked) ────────────────────────

    def test_update_config_inactive_member_returns_403(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """suspended human 멤버 → 403 (세션 fallback 경로 차단).

        ``TokenAuthMiddleware`` 는 토큰 인증 시 비활성을 거부하지만 세션 쿠키
        fallback 에서는 만료만 보므로, ``MemberStatus.ACTIVE`` 가 아닌 멤버는
        명시적으로 403 으로 차단되어야 한다 (require_audit_read #1359 4차 fix
        패턴 답습).
        """
        client.cookies.set("ante_session", "inactive-session-id")
        resp = client.put(_CONFIG_PATH, json=_VALID_CONFIG_PAYLOAD)
        assert resp.status_code == 403, resp.text
        assert dynamic_config.set_calls == []
        client.cookies.delete("ante_session")

    # 422 — 인증 통과 + body invalid ─────────────────────────────────

    def test_update_config_master_invalid_body_returns_422(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """master + body 가 JSON object 가 아님 → 422."""
        resp = client.put(
            _CONFIG_PATH,
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert dynamic_config.set_calls == []

    def test_update_config_master_empty_body_returns_422(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        resp = client.put(
            _CONFIG_PATH,
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert dynamic_config.set_calls == []

    def test_update_config_master_malformed_json_returns_422(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        resp = client.put(
            _CONFIG_PATH,
            content=b"{not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert dynamic_config.set_calls == []

    def test_update_config_master_missing_value_returns_422(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """master + ``value`` 누락 → 422 (Pydantic required field)."""
        resp = client.put(
            _CONFIG_PATH,
            json={"category": "system"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert dynamic_config.set_calls == []

    # 404 — master + missing key ─────────────────────────────────────

    def test_update_config_master_unknown_key_returns_404(
        self, client: TestClient, dynamic_config: FakeDynamicConfig
    ) -> None:
        """master 인증 통과 + 존재하지 않는 키 → 404, ``set`` 미호출."""
        resp = client.put(
            "/api/config/no.such.key",
            json=_VALID_CONFIG_PAYLOAD,
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404, resp.text
        assert dynamic_config.set_calls == []


# ── #1374: POST /api/reports scope-aware 인증 매트릭스 ──────────────────


_VALID_REPORT_PAYLOAD: dict = {
    "strategy_name": "auth_matrix_probe",
    "strategy_version": "0.1.0",
    "strategy_path": "strategies/auth_probe.py",
    "backtest_period": "auth matrix probe",
    "total_return_pct": 0.0,
    "total_trades": 0,
    "summary": "auth matrix probe",
    "rationale": "ensure report:write scope is enforced",
    "detail_json": "{}",
}
_REPORT_PATH = "/api/reports"


class TestSubmitReportAuthMatrix:
    """``POST /api/reports`` 는 scope-aware 인증 가드를 따른다 (#1374).

    spec ``docs/specs/member/02-design-decisions.md:210-227`` 의
    ``require_scope`` predicate 와 정합:
    - master role → 통과
    - human type → 통과 (scope 무관)
    - agent + ``report:write`` ∈ scopes → 통과 (전략 리서치 agent 의 정상 경로)
    - 그 외 → 403

    raw body 패턴 + auth-first: 인증 가드가 body validation 보다 먼저 실행되어
    unauth + bad-body 시 401 우선. 401/403 시 ``report_store.submit`` 미호출
    (mock spy 검증).
    """

    # 401 — 인증 자체가 없음 ─────────────────────────────────────────

    def test_submit_report_unauth_returns_401(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        resp = client.post(_REPORT_PATH, json=_VALID_REPORT_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert report_store.submit_calls == []

    def test_submit_report_invalid_bearer_returns_401(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert report_store.submit_calls == []

    def test_submit_report_invalid_session_cookie_returns_401(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.post(_REPORT_PATH, json=_VALID_REPORT_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert report_store.submit_calls == []
        client.cookies.delete("ante_session")

    def test_submit_report_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        report_store: FakeReportStore,
    ) -> None:
        """``session_service is None`` 배포 + 쿠키만 → 401 (cookie fallback skip)."""
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.post(_REPORT_PATH, json=_VALID_REPORT_PAYLOAD)
        assert resp.status_code == 401, resp.text
        assert report_store.submit_calls == []
        client_no_session_service.cookies.delete("ante_session")

    # auth-first: bad body 라도 401 우선 ─────────────────────────────

    def test_submit_report_unauth_invalid_body_returns_401(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """unauth + body invalid → 401 (NOT 422). update_config 패턴 답습."""
        resp = client.post(_REPORT_PATH, json=["not", "an", "object"])
        assert resp.status_code == 401, (
            f"인증 가드가 body validation 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert report_store.submit_calls == []

    def test_submit_report_unauth_malformed_json_returns_401(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            _REPORT_PATH,
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert report_store.submit_calls == []

    # 200 (실제 POST 는 201) — master 인증 통과 ──────────────────────

    def test_submit_report_master_bearer_succeeds(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["strategy"] == "auth_matrix_probe"
        assert body["status"] == "submitted"
        assert len(report_store.submit_calls) == 1
        assert report_store.submit_calls[-1].submitted_by == "master-user"

    def test_submit_report_master_session_cookie_succeeds(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post(_REPORT_PATH, json=_VALID_REPORT_PAYLOAD)
        assert resp.status_code == 201, resp.text
        assert report_store.submit_calls[-1].submitted_by == "master-user"
        client.cookies.delete("ante_session")

    # 201 — human (scope 무관) 통과 ──────────────────────────────────

    def test_submit_report_human_bearer_succeeds(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """spec predicate: human 멤버는 scope 검증을 무조건 통과한다."""
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer human-token"},
        )
        assert resp.status_code == 201, resp.text
        assert report_store.submit_calls[-1].submitted_by == "human-admin"

    # 201 — agent + report:write scope ───────────────────────────────

    def test_submit_report_agent_with_report_write_succeeds(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """agent + ``report:write`` ∈ scopes → 통과 (spec predicate 정합).

        전략 리서치 agent 는 spec ``02-design-decisions.md:226-227`` 가 명시한
        대로 ``report:write`` scope 만 보유해도 정상 제출이 가능해야 한다.
        """
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer agent-report-token"},
        )
        assert resp.status_code == 201, resp.text
        assert report_store.submit_calls[-1].submitted_by == "agent-report"

    # 403 — agent without scope ──────────────────────────────────────

    def test_submit_report_agent_without_report_write_returns_403(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """agent + scope 미보유 → 403 (spec predicate 정합)."""
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert report_store.submit_calls == []

    def test_submit_report_agent_with_other_scope_returns_403(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """agent + 다른 scope (config:write) → 403.

        ``report:write`` 가 아닌 scope 는 본 라우트 경로를 열지 않아야 한다.
        """
        resp = client.post(
            _REPORT_PATH,
            json=_VALID_REPORT_PAYLOAD,
            headers={"Authorization": "Bearer agent-config-token"},
        )
        assert resp.status_code == 403, resp.text
        assert report_store.submit_calls == []

    # 403 — inactive 멤버 (suspended/revoked) ────────────────────────

    def test_submit_report_inactive_member_returns_403(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """suspended human 멤버 → 403 (세션 fallback 경로 차단).

        ``TokenAuthMiddleware`` 는 토큰 인증 시 비활성을 거부하지만 세션 쿠키
        fallback 에서는 만료만 보므로, ``MemberStatus.ACTIVE`` 가 아닌 멤버는
        명시적으로 403 으로 차단되어야 한다 (require_audit_read #1359 4차 fix
        패턴 답습).
        """
        client.cookies.set("ante_session", "inactive-session-id")
        resp = client.post(_REPORT_PATH, json=_VALID_REPORT_PAYLOAD)
        assert resp.status_code == 403, resp.text
        assert report_store.submit_calls == []
        client.cookies.delete("ante_session")

    # 422 — 인증 통과 + body invalid ─────────────────────────────────

    def test_submit_report_master_invalid_body_returns_422(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """master + body 가 JSON object 가 아님 → 422."""
        resp = client.post(
            _REPORT_PATH,
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert report_store.submit_calls == []

    def test_submit_report_master_empty_body_returns_422(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        resp = client.post(
            _REPORT_PATH,
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert report_store.submit_calls == []

    def test_submit_report_master_malformed_json_returns_422(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        resp = client.post(
            _REPORT_PATH,
            content=b"{not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert report_store.submit_calls == []

    def test_submit_report_master_missing_required_returns_422(
        self, client: TestClient, report_store: FakeReportStore
    ) -> None:
        """master + 필수 필드 누락 → 422 (Pydantic required field)."""
        resp = client.post(
            _REPORT_PATH,
            json={"summary": "no required fields"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert report_store.submit_calls == []


# ── #1375: POST /api/system/halt + /clear-halt 인증 매트릭스 ────────────


_HALT_PATH = "/api/system/halt"
_CLEAR_HALT_PATH = "/api/system/clear-halt"


class TestSystemHaltAuthMatrix:
    """``POST /api/system/halt`` 는 master-only 인증 가드를 따른다 (#1375).

    oracle A7 finding: 익명 호출이 ``account_service.suspend_all`` 을 그대로
    실행해 모든 계좌를 SUSPENDED 로 전환할 수 있었다. 본 매트릭스는
    ``submit_report`` (#1374) / ``update_config`` (#1373) 와 동일한 raw body
    + auth-first 패턴을 보장한다.

    401/403 시 ``account_service.suspend_all`` 이 호출되지 않음을 mock spy
    (``suspend_all_calls``) 로 검증한다. ``reason`` 은 optional 이므로 빈
    body / 빈 JSON object 는 default ``""`` 로 200 을 받는다 (기존 동작 보존).
    """

    # 401 — 인증 자체가 없음 ─────────────────────────────────────────

    def test_halt_unauth_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(_HALT_PATH, json={"reason": "probe"})
        assert resp.status_code == 401, resp.text
        assert account_service.suspend_all_calls == []

    def test_halt_invalid_bearer_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _HALT_PATH,
            json={"reason": "probe"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert account_service.suspend_all_calls == []

    def test_halt_invalid_session_cookie_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.post(_HALT_PATH, json={"reason": "probe"})
        assert resp.status_code == 401, resp.text
        assert account_service.suspend_all_calls == []
        client.cookies.delete("ante_session")

    def test_halt_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """``session_service is None`` 배포 + 쿠키만 → 401 (cookie fallback skip)."""
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.post(_HALT_PATH, json={"reason": "probe"})
        assert resp.status_code == 401, resp.text
        assert account_service.suspend_all_calls == []
        client_no_session_service.cookies.delete("ante_session")

    # auth-first: bad body 라도 401 우선 ─────────────────────────────

    def test_halt_unauth_invalid_body_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """unauth + body invalid → 401 (NOT 422). submit_report 패턴 답습."""
        resp = client.post(_HALT_PATH, json=["not", "an", "object"])
        assert resp.status_code == 401, (
            f"인증 가드가 body validation 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert account_service.suspend_all_calls == []

    def test_halt_unauth_malformed_json_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """unauth + malformed JSON → 401 (NOT 422)."""
        resp = client.post(
            _HALT_PATH,
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert account_service.suspend_all_calls == []

    # 200 — master 인증 통과 ─────────────────────────────────────────

    def test_halt_master_bearer_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _HALT_PATH,
            json={"reason": "emergency"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "halted"
        # changed_at Z suffix 회귀 보호 (#1360).
        assert body["changed_at"].endswith("Z"), (
            f"changed_at 은 Z suffix 여야 한다. got={body['changed_at']!r}"
        )
        assert "+00:00" not in body["changed_at"]
        assert len(account_service.suspend_all_calls) == 1
        # caller_id 가 suspended_by 로 전파되어야 한다 (#1375).
        assert account_service.suspend_all_calls[-1]["suspended_by"] == "master-user"

    def test_halt_master_session_cookie_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post(_HALT_PATH, json={"reason": "emergency"})
        assert resp.status_code == 200, resp.text
        assert account_service.suspend_all_calls[-1]["suspended_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_halt_master_empty_body_succeeds_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + 빈 body → 200 (reason optional, 기존 동작 보존)."""
        resp = client.post(
            _HALT_PATH,
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200, resp.text
        assert len(account_service.suspend_all_calls) == 1

    def test_halt_master_empty_object_body_succeeds_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + ``{}`` → 200 (reason 미지정 → default ``""``)."""
        resp = client.post(
            _HALT_PATH,
            json={},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert len(account_service.suspend_all_calls) == 1

    # 422 — 인증 통과 + body invalid ─────────────────────────────────

    def test_halt_master_invalid_body_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + body 가 JSON object 가 아님 → 422."""
        resp = client.post(
            _HALT_PATH,
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_all_calls == []

    def test_halt_master_malformed_json_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _HALT_PATH,
            content=b"{not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert account_service.suspend_all_calls == []

    def test_halt_master_wrong_type_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + ``reason`` 이 string 아님 → 422 (Pydantic type mismatch)."""
        resp = client.post(
            _HALT_PATH,
            json={"reason": 123},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.suspend_all_calls == []

    # 403 — 인증된 non-master ────────────────────────────────────────

    def test_halt_non_master_bearer_returns_403(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _HALT_PATH,
            json={"reason": "probe"},
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert account_service.suspend_all_calls == []


class TestSystemClearHaltAuthMatrix:
    """``POST /api/system/clear-halt`` 는 master-only 인증 가드를 따른다 (#1375).

    ``halt`` 와 동일한 raw-body + auth-first 패턴. 401/403 시
    ``account_service.activate_all`` 이 호출되지 않음을 mock spy
    (``activate_all_calls``) 로 검증한다.
    """

    # 401 — 인증 자체가 없음 ─────────────────────────────────────────

    def test_clear_halt_unauth_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(_CLEAR_HALT_PATH, json={"reason": "probe"})
        assert resp.status_code == 401, resp.text
        assert account_service.activate_all_calls == []

    def test_clear_halt_invalid_bearer_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            json={"reason": "probe"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, resp.text
        assert account_service.activate_all_calls == []

    def test_clear_halt_invalid_session_cookie_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.post(_CLEAR_HALT_PATH, json={"reason": "probe"})
        assert resp.status_code == 401, resp.text
        assert account_service.activate_all_calls == []
        client.cookies.delete("ante_session")

    def test_clear_halt_session_service_none_no_bearer_returns_401(
        self,
        client_no_session_service: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """``session_service is None`` 배포 + 쿠키만 → 401 (cookie fallback skip)."""
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = client_no_session_service.post(
            _CLEAR_HALT_PATH, json={"reason": "probe"}
        )
        assert resp.status_code == 401, resp.text
        assert account_service.activate_all_calls == []
        client_no_session_service.cookies.delete("ante_session")

    # auth-first: bad body 라도 401 우선 ─────────────────────────────

    def test_clear_halt_unauth_invalid_body_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """unauth + body invalid → 401 (NOT 422). submit_report 패턴 답습."""
        resp = client.post(_CLEAR_HALT_PATH, json=["not", "an", "object"])
        assert resp.status_code == 401, (
            f"인증 가드가 body validation 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert account_service.activate_all_calls == []

    def test_clear_halt_unauth_malformed_json_returns_401(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert account_service.activate_all_calls == []

    # 200 — master 인증 통과 ─────────────────────────────────────────

    def test_clear_halt_master_bearer_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            json={"reason": "recovered"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "halt_cleared"
        # changed_at Z suffix 회귀 보호 (#1360).
        assert body["changed_at"].endswith("Z"), (
            f"changed_at 은 Z suffix 여야 한다. got={body['changed_at']!r}"
        )
        assert "+00:00" not in body["changed_at"]
        assert len(account_service.activate_all_calls) == 1
        assert account_service.activate_all_calls[-1]["activated_by"] == "master-user"

    def test_clear_halt_master_session_cookie_succeeds(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post(_CLEAR_HALT_PATH, json={"reason": "recovered"})
        assert resp.status_code == 200, resp.text
        assert account_service.activate_all_calls[-1]["activated_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_clear_halt_master_empty_body_succeeds_with_default_reason(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        """master + 빈 body → 200 (reason optional, 기존 동작 보존)."""
        resp = client.post(
            _CLEAR_HALT_PATH,
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200, resp.text
        assert len(account_service.activate_all_calls) == 1

    # 422 — 인증 통과 + body invalid ─────────────────────────────────

    def test_clear_halt_master_invalid_body_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert account_service.activate_all_calls == []

    def test_clear_halt_master_malformed_json_returns_422(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            content=b"{not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert account_service.activate_all_calls == []

    # 403 — 인증된 non-master ────────────────────────────────────────

    def test_clear_halt_non_master_bearer_returns_403(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        resp = client.post(
            _CLEAR_HALT_PATH,
            json={"reason": "probe"},
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, resp.text
        assert account_service.activate_all_calls == []
