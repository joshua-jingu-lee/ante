"""POST /api/treasury/bots/{bot_id}/allocate, /deallocate 입력 invariant 회귀 테스트.

이슈 #1411: `amount`가 raw JSON `NaN`/`Infinity`/`-Infinity`로 들어와도
422가 아닌 500을 반환하고, IPC/CLI 경유 호출은 그대로 `Treasury.allocate`에
전달돼 `budget.allocated += nan`으로 state를 오염시키는 결함을 막는다.

Web API 계층 입력 invariant(``Annotated[float, Field(gt=0, allow_inf_nan=False)]``)
가 NaN/±Inf/0/음수를 422로 거부함을 회귀 검증한다. Service 계층의
``math.isfinite`` 가드는 ``tests/unit/test_treasury.py``에서 검증한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field as dc_field

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.member.models import MemberRole  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# 인증 가드(#1372/#1407) — POST /api/treasury/bots/<bot>/(allocate|deallocate)는
# master Bearer 또는 유효한 ante_session 쿠키가 필요하다. 본 모듈은 입력
# invariant(NaN/±Inf/0/음수 → 422) 회귀 본질을 검증하므로 master 토큰을
# default 헤더로 적용한다.
_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


@dataclass
class _StubMember:
    member_id: str
    role: str = "default"
    type: str = "agent"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = dc_field(default_factory=list)


class _StubMemberService:
    def __init__(self) -> None:
        self._members: dict[str, _StubMember] = {
            "master-user": _StubMember(
                member_id="master-user", role=MemberRole.MASTER.value
            ),
        }
        self._tokens: dict[str, str] = {"master-token": "master-user"}

    async def authenticate(self, token: str) -> _StubMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _StubMember | None:
        return self._members.get(member_id)


@dataclass
class _StubBudget:
    bot_id: str
    allocated: float = 0.0
    available: float = 0.0


class FakeTreasury:
    """allocate/deallocate Web API 경로용 Treasury stub.

    Service 계층의 finite-positive 가드(``math.isfinite``)도 함께 적용해
    Web 계층이 1차 차단을 못 했을 때 state 오염을 방지한다 — Web 라우트가
    422로 막아주면 본 stub의 allocate/deallocate는 호출되지 않는 게 정상.
    """

    def __init__(self, initial_unallocated: float = 10_000_000.0) -> None:
        self._unallocated: float = initial_unallocated
        self._budgets: dict[str, _StubBudget] = {}

    @property
    def unallocated(self) -> float:
        return self._unallocated

    def get_budget(self, bot_id: str) -> _StubBudget | None:
        return self._budgets.get(bot_id)

    def list_budgets(self) -> list[_StubBudget]:
        return list(self._budgets.values())

    def get_summary(self) -> dict:
        return {"account_balance": self._unallocated, "unallocated": self._unallocated}

    async def get_latest_snapshot(self) -> None:
        return None

    async def allocate(self, bot_id: str, amount: float) -> bool:
        # Defense in depth: Web 라우트가 막지 못한 invariant를 service에서도 차단.
        if not math.isfinite(amount) or amount <= 0 or self._unallocated < amount:
            return False
        budget = self._budgets.setdefault(bot_id, _StubBudget(bot_id=bot_id))
        budget.allocated += amount
        budget.available += amount
        self._unallocated -= amount
        return True

    async def deallocate(self, bot_id: str, amount: float) -> bool:
        budget = self._budgets.get(bot_id)
        if (
            not budget
            or not math.isfinite(amount)
            or amount <= 0
            or budget.available < amount
        ):
            return False
        budget.allocated -= amount
        budget.available -= amount
        self._unallocated += amount
        return True


@pytest.fixture
def treasury() -> FakeTreasury:
    return FakeTreasury()


@pytest.fixture
def client(treasury: FakeTreasury) -> TestClient:
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)
    client.headers.update(_MASTER_HEADERS)
    return client


# ── /allocate: invariant 회귀 ──────────────────────────────────


def test_allocate_rejects_nan_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": NaN}` → 422 (allow_inf_nan=False).

    표준 JSON 인코더는 NaN을 거부하므로 raw body로 직접 보낸다. Python json/
    Pydantic은 비표준 토큰을 파싱할 수 있고 invariant는 라우트에서 막아야 한다.
    """
    resp = client.post(
        "/api/treasury/bots/bot1/allocate",
        content='{"amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    # state 오염 없음
    assert treasury.unallocated == 10_000_000.0
    assert treasury.get_budget("bot1") is None


def test_allocate_rejects_positive_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": Infinity}` → 422 (allow_inf_nan=False)."""
    resp = client.post(
        "/api/treasury/bots/bot1/allocate",
        content='{"amount": Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.unallocated == 10_000_000.0


def test_allocate_rejects_negative_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": -Infinity}` → 422 (allow_inf_nan=False)."""
    resp = client.post(
        "/api/treasury/bots/bot1/allocate",
        content='{"amount": -Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.unallocated == 10_000_000.0


def test_allocate_rejects_zero_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": 0}` → 422 (Field(gt=0))."""
    resp = client.post("/api/treasury/bots/bot1/allocate", json={"amount": 0})
    assert resp.status_code == 422
    assert treasury.unallocated == 10_000_000.0


def test_allocate_rejects_negative_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": -1}` → 422 (Field(gt=0))."""
    resp = client.post("/api/treasury/bots/bot1/allocate", json={"amount": -1})
    assert resp.status_code == 422
    assert treasury.unallocated == 10_000_000.0


def test_allocate_accepts_positive(client: TestClient, treasury: FakeTreasury) -> None:
    """body `{"amount": 1000}` → 200 (정상 경로 회귀 보존)."""
    resp = client.post("/api/treasury/bots/bot1/allocate", json={"amount": 1000.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_id"] == "bot1"
    assert data["allocated"] == 1000.0
    assert data["available"] == 1000.0
    assert treasury.unallocated == 10_000_000.0 - 1000.0


# ── /deallocate: invariant 회귀 ────────────────────────────────


def test_deallocate_rejects_nan_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": NaN}` → 422 (allow_inf_nan=False)."""
    resp = client.post(
        "/api/treasury/bots/bot1/deallocate",
        content='{"amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_deallocate_rejects_positive_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": Infinity}` → 422."""
    resp = client.post(
        "/api/treasury/bots/bot1/deallocate",
        content='{"amount": Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_deallocate_rejects_negative_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": -Infinity}` → 422."""
    resp = client.post(
        "/api/treasury/bots/bot1/deallocate",
        content='{"amount": -Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_deallocate_rejects_zero_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": 0}` → 422 (Field(gt=0))."""
    resp = client.post("/api/treasury/bots/bot1/deallocate", json={"amount": 0})
    assert resp.status_code == 422


def test_deallocate_rejects_negative_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """body `{"amount": -1}` → 422 (Field(gt=0))."""
    resp = client.post("/api/treasury/bots/bot1/deallocate", json={"amount": -1})
    assert resp.status_code == 422


# ── 거부 시 state 미오염 ───────────────────────────────────────


def test_allocate_nan_does_not_mutate_state() -> None:
    """`{"amount": NaN}` 요청 후 _unallocated/budgets가 호출 전 상태 유지."""
    treasury = FakeTreasury(initial_unallocated=100.0)
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)
    client.headers.update(_MASTER_HEADERS)

    resp = client.post(
        "/api/treasury/bots/bot1/allocate",
        content='{"amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.unallocated == 100.0
    assert treasury.get_budget("bot1") is None


# ── auth-first invariant: unauth + 잘못된 body → 401 우선 ──────


def test_allocate_unauth_nan_returns_401_not_422() -> None:
    """인증 없는 호출 + body NaN → 401 우선(body validation 전에 차단). #1372."""
    treasury = FakeTreasury()
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)
    # 인증 헤더 의도적으로 제거.

    resp = client.post(
        "/api/treasury/bots/bot1/allocate",
        content='{"amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_deallocate_unauth_nan_returns_401_not_422() -> None:
    """deallocate: 인증 없는 호출 + body NaN → 401."""
    treasury = FakeTreasury()
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)

    resp = client.post(
        "/api/treasury/bots/bot1/deallocate",
        content='{"amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


# ── OpenAPI schema 회귀 ────────────────────────────────────────


def test_openapi_budget_change_request_schema_has_exclusive_minimum(
    client: TestClient,
) -> None:
    """BudgetChangeRequest.properties.amount.exclusiveMinimum == 0 (#1411)."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    budget_change = schema["components"]["schemas"]["BudgetChangeRequest"]
    amount_prop = budget_change["properties"]["amount"]
    assert amount_prop["exclusiveMinimum"] == 0
    assert "finite" in amount_prop["description"].lower()
