"""/api/system/health — DB/Broker 실제 상태 반영 검증 (#1100)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeAccount:
    account_id: str


class _FakeDBOk:
    """정상 동작하는 fake DB (fetch_one 성공)."""

    async def fetch_one(self, _query: str) -> dict:
        return {"1": 1}


class _FakeDBFail:
    """fetch_one이 예외를 던지는 fake DB."""

    async def fetch_one(self, _query: str) -> dict:
        raise RuntimeError("db unavailable")


def _make_account_service(
    accounts: list[FakeAccount],
    brokers: dict[str, object],
) -> AsyncMock:
    """list()와 get_broker()를 제공하는 fake account_service 생성."""
    svc = AsyncMock()
    svc.list = AsyncMock(return_value=accounts)

    async def _get_broker(account_id: str) -> object:
        return brokers[account_id]

    svc.get_broker = AsyncMock(side_effect=_get_broker)
    return svc


class _ConnectedBroker:
    connected = True


class _DisconnectedBroker:
    connected = False


class TestSystemHealth:
    def test_db_ok_and_broker_connected_returns_ok_true(self) -> None:
        """DB 정상 + broker 중 1개 이상 연결 → ok=True."""
        account_service = _make_account_service(
            accounts=[FakeAccount(account_id="a1"), FakeAccount(account_id="a2")],
            brokers={"a1": _DisconnectedBroker(), "a2": _ConnectedBroker()},
        )
        app = create_app(db=_FakeDBOk(), account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"ok": True, "checks": {"db": True, "broker": True}}

    def test_db_failure_returns_ok_false(self) -> None:
        """DB fetch 실패 → checks.db=False, ok=False."""
        account_service = _make_account_service(
            accounts=[FakeAccount(account_id="a1")],
            brokers={"a1": _ConnectedBroker()},
        )
        app = create_app(db=_FakeDBFail(), account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["checks"]["db"] is False
        assert data["checks"]["broker"] is True

    def test_all_brokers_disconnected_returns_ok_false(self) -> None:
        """모든 broker 연결이 끊김 → checks.broker=False, ok=False."""
        account_service = _make_account_service(
            accounts=[FakeAccount(account_id="a1"), FakeAccount(account_id="a2")],
            brokers={"a1": _DisconnectedBroker(), "a2": _DisconnectedBroker()},
        )
        app = create_app(db=_FakeDBOk(), account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["checks"]["db"] is True
        assert data["checks"]["broker"] is False

    def test_account_service_none_returns_broker_false(self) -> None:
        """account_service가 주입되지 않음 → broker=False, ok=False."""
        app = create_app(db=_FakeDBOk())
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checks"]["broker"] is False
        assert data["ok"] is False

    def test_account_service_list_raises_returns_broker_false(self) -> None:
        """account_service.list() 예외 → 500 아닌 checks.broker=False."""
        svc = AsyncMock()
        svc.list = AsyncMock(side_effect=RuntimeError("account list failed"))
        app = create_app(db=_FakeDBOk(), account_service=svc)
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checks"]["broker"] is False
        assert data["ok"] is False

    def test_get_broker_raises_skips_account(self) -> None:
        """특정 계좌의 get_broker가 실패해도 다음 계좌로 폴백하여 검사한다."""
        accounts = [FakeAccount(account_id="a1"), FakeAccount(account_id="a2")]
        svc = AsyncMock()
        svc.list = AsyncMock(return_value=accounts)

        async def _get_broker(account_id: str) -> object:
            if account_id == "a1":
                raise RuntimeError("broker unavailable")
            return _ConnectedBroker()

        svc.get_broker = AsyncMock(side_effect=_get_broker)

        app = create_app(db=_FakeDBOk(), account_service=svc)
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["checks"]["broker"] is True

    def test_no_db_state_returns_db_false(self) -> None:
        """app.state.db가 없음 → checks.db=False."""
        app = create_app()  # db 미주입
        client = TestClient(app)

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checks"] == {"db": False, "broker": False}
        assert data["ok"] is False
