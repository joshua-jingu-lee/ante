"""Kill Switch 응답 ``changed_at`` Z suffix 검증 (Refs #1360).

SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT는
``changed_at``을 ``string (ISO 8601 UTC)``로 정의하고 ``Z`` suffix를 사용한다.

Python ``datetime.isoformat()``은 UTC offset을 ``+00:00``으로 직렬화하므로
``_kill_switch_payload``는 변환 helper를 통해 ``Z`` suffix로 통일해야 한다.

Web API (`src/ante/web/routes/system.py`)와 IPC registry
(`src/ante/ipc/registry.py`) 양쪽이 동일 SSOT shape을 공유하므로 두 표면 모두
검증한다.

#1375: ``POST /api/system/halt`` 와 ``/clear-halt`` 는 master 인증이 필요해
졌다. 본 모듈은 timestamp Z suffix invariant 를 검증하므로 master 인증
fixture 를 통과시키고 changed_at 회귀만 본다 — IPC 경로는 web 인증과
무관하므로 그대로 유지한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

# #1375: master 인증 통과를 위한 최소 stub.
_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


@dataclass
class _StubMember:
    member_id: str
    type: str = "human"
    role: str = "master"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _StubMemberService:
    """``require_master_caller`` 통과 최소 stub (#1375)."""

    def __init__(self) -> None:
        self._members: dict[str, _StubMember] = {
            "master-user": _StubMember(member_id="master-user")
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
    app = create_app(
        account_service=account_service,
        member_service=_StubMemberService(),
    )
    return TestClient(app)


class TestWebKillSwitchChangedAtZSuffix:
    """POST /api/system/halt + /api/system/clear-halt ``changed_at`` Z suffix."""

    def test_halt_changed_at_uses_z_suffix(self, client) -> None:
        resp = client.post(
            "/api/system/halt", json={"reason": ""}, headers=_MASTER_HEADERS
        )
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
        resp = client.post(
            "/api/system/clear-halt", json={"reason": ""}, headers=_MASTER_HEADERS
        )
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
