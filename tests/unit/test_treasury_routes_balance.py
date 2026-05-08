"""POST /api/treasury/balance 입력 invariant 회귀 테스트.

이슈 #1340: 음수/NaN/Inf 잔고가 200으로 수락되어 treasury state가 오염되는 문제를
입력 invariant(`Annotated[float, Field(ge=0, allow_inf_nan=False)]`)로 막는다.
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

# 인증 가드(#1352) 도입으로 POST /api/treasury/balance는 master Bearer 또는
# 유효한 ante_session 쿠키가 필요하다. 본 모듈은 입력 invariant(음수/NaN/Inf
# 422) 회귀 본질을 검증하므로 master 토큰을 default 헤더로 적용한다.
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


class FakeTreasury:
    """테스트용 Treasury stub. 거부된 요청이 state를 변경하지 않는지 확인하기 위해
    인메모리 잔고/미할당만 보관한다."""

    def __init__(self, initial_balance: float = 0.0) -> None:
        self._balance: float = initial_balance
        self._unallocated: float = initial_balance

    @property
    def account_balance(self) -> float:
        return self._balance

    @property
    def unallocated(self) -> float:
        return self._unallocated

    async def set_account_balance(self, balance: float) -> None:
        # 라우트 단계에서 422로 거부되면 이 메서드는 호출되지 않아야 한다.
        # 호출이 들어오면 정상 경로로 mutate한다.
        if not (math.isfinite(balance) and balance >= 0):
            raise ValueError(
                f"account balance must be finite and >= 0, got {balance!r}"
            )
        self._balance = balance
        self._unallocated = balance

    def list_budgets(self) -> list:
        return []

    def get_summary(self) -> dict:
        return {"account_balance": self._balance, "unallocated": self._unallocated}

    async def get_latest_snapshot(self) -> None:
        return None


@pytest.fixture
def treasury() -> FakeTreasury:
    return FakeTreasury()


@pytest.fixture
def client(treasury: FakeTreasury) -> TestClient:
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)
    client.headers.update(_MASTER_HEADERS)
    return client


def test_set_balance_rejects_negative_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """balance=-1.0 → 422 (Field(ge=0))."""
    resp = client.post("/api/treasury/balance", json={"balance": -1.0})
    assert resp.status_code == 422
    assert treasury.account_balance == 0.0


def test_set_balance_rejects_nan_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """balance=NaN → 422 (allow_inf_nan=False).

    표준 JSON 인코더는 NaN을 거부하므로 raw body(`NaN`)를 직접 보낸다.
    Python json/Pydantic은 비표준 토큰을 파싱할 수 있고 invariant는
    라우트에서 막아야 한다.
    """
    resp = client.post(
        "/api/treasury/balance",
        content='{"balance": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.account_balance == 0.0


def test_set_balance_rejects_positive_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """balance=+Inf → 422 (allow_inf_nan=False)."""
    resp = client.post(
        "/api/treasury/balance",
        content='{"balance": Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.account_balance == 0.0


def test_set_balance_rejects_negative_inf_with_422(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """balance=-Inf → 422 (allow_inf_nan=False)."""
    resp = client.post(
        "/api/treasury/balance",
        content='{"balance": -Infinity}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert treasury.account_balance == 0.0


def test_set_balance_rejected_does_not_mutate_state() -> None:
    """초기 잔고 100인 treasury에 -1.0 요청 → 422,
    treasury.account_balance/unallocated가 100 그대로 유지."""
    treasury = FakeTreasury(initial_balance=100.0)
    app = create_app(treasury=treasury, member_service=_StubMemberService())
    client = TestClient(app)
    client.headers.update(_MASTER_HEADERS)

    resp = client.post("/api/treasury/balance", json={"balance": -1.0})
    assert resp.status_code == 422
    assert treasury.account_balance == 100.0
    assert treasury.unallocated == 100.0


def test_set_balance_accepts_zero(client: TestClient, treasury: FakeTreasury) -> None:
    """balance=0 → 200 (ge=0 경계 허용)."""
    resp = client.post("/api/treasury/balance", json={"balance": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_balance"] == 0
    assert treasury.account_balance == 0.0


def test_set_balance_accepts_positive(
    client: TestClient, treasury: FakeTreasury
) -> None:
    """balance=10000000 → 200 (정상 경로)."""
    resp = client.post("/api/treasury/balance", json={"balance": 10_000_000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_balance"] == 10_000_000
    assert treasury.account_balance == 10_000_000
