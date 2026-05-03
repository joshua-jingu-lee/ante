"""시스템 설정 API 테스트 (halt/activate + 동적 설정)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeDynamicConfig:
    """테스트용 DynamicConfigService stub."""

    def __init__(self) -> None:
        self._configs: dict[str, dict] = {}

    async def get_all(self) -> list[dict]:
        return [
            {
                "key": key,
                "value": item["value"],
                "category": item["category"],
                "updated_at": "2025-01-01T00:00:00",
            }
            for key, item in self._configs.items()
        ]

    async def exists(self, key: str) -> bool:
        return key in self._configs

    async def get(self, key: str, default: object = None) -> object:
        if key in self._configs:
            return self._configs[key]["value"]
        return default

    async def set(
        self,
        key: str,
        value: object,
        category: str = "",
        changed_by: str = "",
    ) -> None:
        self._configs[key] = {"value": value, "category": category}


@pytest.fixture
def account_service():
    mock = AsyncMock()
    # Refs #1213: list[dict] 반환 타입 (account_id, previous_status, status, changed).
    mock.suspend_all = AsyncMock(
        return_value=[
            {
                "account_id": "domestic",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            }
        ]
    )
    mock.activate_all = AsyncMock(
        return_value=[
            {
                "account_id": "domestic",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            }
        ]
    )
    return mock


@pytest.fixture
def dynamic_config():
    return FakeDynamicConfig()


@pytest.fixture
def client(account_service, dynamic_config):
    app = create_app(account_service=account_service, dynamic_config=dynamic_config)
    return TestClient(app)


class TestHaltClearHalt:
    """POST /api/system/halt + /api/system/clear-halt SSOT 응답 shape 검증.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT.
    """

    def test_halt(self, client, account_service):
        """POST /halt로 전체 거래 중지."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": "긴급 중지"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halted"
        assert data["accounts_changed"] == 1
        assert "changed_at" in data
        assert data["accounts"] == [
            {
                "account_id": "domestic",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            }
        ]
        account_service.suspend_all.assert_called_once()

    def test_clear_halt(self, client, account_service):
        """POST /clear-halt로 전역 정지 해제."""
        resp = client.post(
            "/api/system/clear-halt",
            json={"reason": "재개"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halt_cleared"
        assert data["accounts_changed"] == 1
        assert "changed_at" in data
        assert data["accounts"] == [
            {
                "account_id": "domestic",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            }
        ]
        account_service.activate_all.assert_called_once()

    def test_halt_clear_halt_lifecycle(self, client, account_service):
        """halt → clear-halt lifecycle."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "halted"

        resp = client.post(
            "/api/system/clear-halt",
            json={"reason": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "halt_cleared"

    def test_legacy_activate_route_removed(self, client):
        """legacy POST /api/system/activate는 hard remove (SSOT 정책)."""
        resp = client.post("/api/system/activate", json={"reason": ""})
        assert resp.status_code == 404

    def test_legacy_kill_switch_route_absent(self, client):
        """legacy POST /api/system/kill-switch는 등록되지 않음 (SSOT 정책)."""
        resp = client.post("/api/system/kill-switch", json={"action": "halt"})
        assert resp.status_code == 404


class TestDynamicConfig:
    def test_list_configs(self, client, dynamic_config):
        """설정 목록 조회."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["configs"]) == 1
        assert data["configs"][0]["key"] == "risk.max_mdd"
        assert data["configs"][0]["value"] == 0.1

    def test_empty_configs(self, client):
        """빈 설정 목록."""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["configs"] == []

    def test_update_config(self, client, dynamic_config):
        """설정 값 변경."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": 0.05},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "risk.max_mdd"
        assert data["old_value"] == 0.1
        assert data["new_value"] == 0.05

    def test_update_nonexistent(self, client):
        """존재하지 않는 설정 → 404."""
        resp = client.put(
            "/api/config/nonexistent.key",
            json={"value": "test"},
        )
        assert resp.status_code == 404
