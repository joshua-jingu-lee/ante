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
    mock.suspend_all = AsyncMock(return_value=1)
    mock.activate_all = AsyncMock(return_value=1)
    return mock


@pytest.fixture
def dynamic_config():
    return FakeDynamicConfig()


@pytest.fixture
def client(account_service, dynamic_config):
    app = create_app(account_service=account_service, dynamic_config=dynamic_config)
    return TestClient(app)


class TestHaltActivate:
    def test_halt(self, client, account_service):
        """POST /halt로 전체 거래 중지."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": "긴급 중지"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "suspended" in data["status"]
        assert "changed_at" in data
        account_service.suspend_all.assert_called_once()

    def test_activate(self, client, account_service):
        """POST /activate로 거래 재개."""
        resp = client.post(
            "/api/system/activate",
            json={"reason": "재개"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "activated" in data["status"]
        account_service.activate_all.assert_called_once()

    def test_halt_activate_lifecycle(self, client, account_service):
        """halt → activate lifecycle."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": ""},
        )
        assert resp.status_code == 200
        assert "suspended" in resp.json()["status"]

        resp = client.post(
            "/api/system/activate",
            json={"reason": ""},
        )
        assert resp.status_code == 200
        assert "activated" in resp.json()["status"]


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
