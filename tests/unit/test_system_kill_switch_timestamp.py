"""Kill Switch 응답 ``changed_at`` Z suffix 검증 (Refs #1360).

SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT는
``changed_at``을 ``string (ISO 8601 UTC)``로 정의하고 ``Z`` suffix를 사용한다.

Python ``datetime.isoformat()``은 UTC offset을 ``+00:00``으로 직렬화하므로
``_kill_switch_payload``는 변환 helper를 통해 ``Z`` suffix로 통일해야 한다.

Web API (`src/ante/web/routes/system.py`)와 IPC registry
(`src/ante/ipc/registry.py`) 양쪽이 동일 SSOT shape을 공유하므로 두 표면 모두
검증한다.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.ipc.registry import (  # noqa: E402
    _handle_system_clear_halt,
    _handle_system_halt,
)
from ante.web.app import create_app  # noqa: E402

# RFC 3339 / ISO 8601 + Z suffix를 받는 strict 정규식.
ISO8601_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


@pytest.fixture
def account_service():
    """suspend_all / activate_all stub. Refs #1213 list[dict] shape."""
    mock = AsyncMock()
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
def client(account_service):
    app = create_app(account_service=account_service)
    return TestClient(app)


class TestWebKillSwitchChangedAtZSuffix:
    """POST /api/system/halt + /api/system/clear-halt ``changed_at`` Z suffix."""

    def test_halt_changed_at_uses_z_suffix(self, client) -> None:
        resp = client.post("/api/system/halt", json={"reason": ""})
        assert resp.status_code == 200
        changed_at = resp.json()["changed_at"]
        assert isinstance(changed_at, str)
        assert changed_at.endswith("Z"), (
            f"changed_at은 Z suffix여야 한다. got={changed_at!r}"
        )
        assert "+00:00" not in changed_at
        assert ISO8601_UTC_Z.match(changed_at), (
            f"changed_at이 ISO 8601 UTC + Z suffix 형식이어야 한다. got={changed_at!r}"
        )

    def test_clear_halt_changed_at_uses_z_suffix(self, client) -> None:
        resp = client.post("/api/system/clear-halt", json={"reason": ""})
        assert resp.status_code == 200
        changed_at = resp.json()["changed_at"]
        assert isinstance(changed_at, str)
        assert changed_at.endswith("Z"), (
            f"changed_at은 Z suffix여야 한다. got={changed_at!r}"
        )
        assert "+00:00" not in changed_at
        assert ISO8601_UTC_Z.match(changed_at), (
            f"changed_at이 ISO 8601 UTC + Z suffix 형식이어야 한다. got={changed_at!r}"
        )


class TestIPCKillSwitchChangedAtZSuffix:
    """IPC system.halt / system.clear_halt 핸들러도 동일 shape SSOT."""

    @pytest.mark.asyncio
    async def test_ipc_halt_changed_at_uses_z_suffix(self) -> None:
        svc = AsyncMock()
        svc.account.suspend_all = AsyncMock(
            return_value=[
                {
                    "account_id": "domestic",
                    "previous_status": "active",
                    "status": "suspended",
                    "changed": True,
                }
            ]
        )
        result = await _handle_system_halt(svc, {"reason": "test"}, "tester")
        changed_at = result["changed_at"]
        assert isinstance(changed_at, str)
        assert changed_at.endswith("Z"), (
            f"IPC halt changed_at은 Z suffix여야 한다. got={changed_at!r}"
        )
        assert "+00:00" not in changed_at
        assert ISO8601_UTC_Z.match(changed_at)

    @pytest.mark.asyncio
    async def test_ipc_clear_halt_changed_at_uses_z_suffix(self) -> None:
        svc = AsyncMock()
        svc.account.activate_all = AsyncMock(
            return_value=[
                {
                    "account_id": "domestic",
                    "previous_status": "suspended",
                    "status": "active",
                    "changed": True,
                }
            ]
        )
        result = await _handle_system_clear_halt(svc, {}, "tester")
        changed_at = result["changed_at"]
        assert isinstance(changed_at, str)
        assert changed_at.endswith("Z"), (
            f"IPC clear_halt changed_at은 Z suffix여야 한다. got={changed_at!r}"
        )
        assert "+00:00" not in changed_at
        assert ISO8601_UTC_Z.match(changed_at)
