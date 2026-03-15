"""시스템 설정 API 테스트 (킬스위치 + 동적 설정)."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeSystemState:
    """테스트용 SystemState stub."""

    def __init__(self) -> None:
        self._state = "active"

    @property
    def trading_state(self) -> FakeTradingState:
        return FakeTradingState(self._state)

    async def set_state(
        self, state: object, reason: str = "", changed_by: str = ""
    ) -> None:
        self._state = state.value if hasattr(state, "value") else str(state)


class FakeTradingState:
    def __init__(self, value: str) -> None:
        self.value = value


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
def system_state():
    return FakeSystemState()


@pytest.fixture
def dynamic_config():
    return FakeDynamicConfig()


@pytest.fixture
def client(system_state, dynamic_config):
    app = create_app(system_state=system_state, dynamic_config=dynamic_config)
    return TestClient(app)


class TestKillSwitch:
    def test_halt(self, client, system_state):
        """킬스위치 halt."""
        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "halt", "reason": "긴급 중지"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "halted"
        assert "changed_at" in resp.json()

    def test_activate(self, client, system_state):
        """킬스위치 activate."""
        system_state._state = "halted"
        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "activate", "reason": "재개"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_invalid_action(self, client):
        """잘못된 action → 400."""
        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "invalid"},
        )
        assert resp.status_code == 400

    def test_halt_activate_lifecycle(self, client, system_state):
        """halt → activate lifecycle."""
        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "halt"},
        )
        assert resp.json()["status"] == "halted"

        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "activate"},
        )
        assert resp.json()["status"] == "active"


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
