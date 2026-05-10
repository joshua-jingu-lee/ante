"""Treasury 봇 존재 검증 테스트 (#658, #1372).

존재하지 않는 봇에 대한 예산 할당/회수 시 404를 반환하는지 검증한다.

#1372: ``allocate``/``deallocate`` 라우트가 master 인증 가드를 갖게 된 후에도
기존 봇 존재 검증 시나리오가 통과해야 한다. master Bearer 토큰을 가진
``FakeMember``/``FakeMemberService`` stub을 주입한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeBudget:
    """테스트용 BotBudget."""

    bot_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeTreasury:
    """테스트용 Treasury stub."""

    def __init__(self) -> None:
        self._balance: float = 10_000_000.0
        self._unallocated: float = 10_000_000.0
        self._budgets: dict[str, FakeBudget] = {}

    @property
    def account_balance(self) -> float:
        return self._balance

    def get_summary(self) -> dict:
        return {"account_balance": self._balance}

    async def allocate(self, bot_id: str, amount: float) -> bool:
        if amount <= 0 or self._unallocated < amount:
            return False
        if bot_id not in self._budgets:
            self._budgets[bot_id] = FakeBudget(bot_id=bot_id)
        budget = self._budgets[bot_id]
        budget.allocated += amount
        budget.available += amount
        self._unallocated -= amount
        return True

    async def get_latest_snapshot(self) -> None:
        return None

    async def deallocate(self, bot_id: str, amount: float) -> bool:
        budget = self._budgets.get(bot_id)
        if not budget or amount <= 0 or budget.available < amount:
            return False
        budget.allocated -= amount
        budget.available -= amount
        self._unallocated += amount
        return True

    def get_budget(self, bot_id: str) -> FakeBudget | None:
        return self._budgets.get(bot_id)

    def list_budgets(self) -> list[FakeBudget]:
        return list(self._budgets.values())


class FakeBotManager:
    """테스트용 BotManager stub."""

    def __init__(self, bot_ids: list[str] | None = None) -> None:
        self._bots: dict[str, Any] = {}
        for bid in bot_ids or []:
            self._bots[bid] = {"bot_id": bid, "status": "stopped"}

    def get_bot(self, bot_id: str) -> Any | None:
        return self._bots.get(bot_id)


# ── master 인증 stub (#1372) ─────────────────────────────────────────────


@dataclass
class _FakeMember:
    member_id: str = "master-user"
    type: str = "human"
    role: str = "master"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _FakeMemberService:
    """master 단일 멤버를 가진 ``MemberService`` stub."""

    def __init__(self) -> None:
        self._member = _FakeMember()
        self._tokens = {"master-token": self._member.member_id}

    async def authenticate(self, token: str) -> _FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._member

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _FakeMember | None:
        return self._member if member_id == self._member.member_id else None


@pytest.fixture
def treasury():
    return FakeTreasury()


@pytest.fixture
def bot_manager():
    return FakeBotManager(bot_ids=["existing-bot"])


@pytest.fixture
def member_service():
    return _FakeMemberService()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """master Bearer 토큰 헤더 (#1372)."""
    return {"Authorization": "Bearer master-token"}


@pytest.fixture
def client(treasury, bot_manager, member_service):
    app = create_app(
        treasury=treasury,
        bot_manager=bot_manager,
        member_service=member_service,
    )
    return TestClient(app)


class TestAllocateNonExistentBot:
    """존재하지 않는 봇에 예산 할당 시 404 반환."""

    def test_allocate_nonexistent_bot_returns_404(self, client, auth_headers):
        """존재하지 않는 봇에 allocate 요청 시 404."""
        resp = client.post(
            "/api/treasury/bots/nonexistent-bot/allocate",
            json={"amount": 100_000},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "봇을 찾을 수 없습니다" in resp.json()["detail"]

    def test_allocate_existing_bot_succeeds(self, client, auth_headers):
        """존재하는 봇에 allocate 요청 시 정상 처리."""
        resp = client.post(
            "/api/treasury/bots/existing-bot/allocate",
            json={"amount": 100_000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == "existing-bot"
        assert data["allocated"] == 100_000


class TestDeallocateNonExistentBot:
    """존재하지 않는 봇에서 예산 회수 시 404 반환."""

    def test_deallocate_nonexistent_bot_returns_404(self, client, auth_headers):
        """존재하지 않는 봇에 deallocate 요청 시 404."""
        resp = client.post(
            "/api/treasury/bots/nonexistent-bot/deallocate",
            json={"amount": 100_000},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "봇을 찾을 수 없습니다" in resp.json()["detail"]

    def test_deallocate_existing_bot_with_budget(self, client, auth_headers):
        """존재하는 봇에서 예산 회수 시 정상 처리."""
        # 먼저 예산 할당
        client.post(
            "/api/treasury/bots/existing-bot/allocate",
            json={"amount": 200_000},
            headers=auth_headers,
        )
        # 회수
        resp = client.post(
            "/api/treasury/bots/existing-bot/deallocate",
            json={"amount": 100_000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == "existing-bot"
        assert data["allocated"] == 100_000
