"""strategy.set_status의 IPC 응답·서비스 호출·감사 기록 특성 테스트 (#2683 ①).

서비스는 실제 ``StrategyRegistry.update_status``다. 저장소 조회(``get``)와 DB만
대역이라, 핸들러가 열거형이 아닌 값을 넘기면 서비스의 ``.value``에서 응답이 바뀐다.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.requests import StrategySetStatusRequest
from ante.ipc.server import IPCServer, IPCServerState
from ante.strategy.registry import StrategyRecord, StrategyRegistry, StrategyStatus
from tests.unit.ipc.test_request_model_domain import validation_message

ACTOR = "ops-lead"
UPDATE_SQL = "UPDATE strategies SET status = ? WHERE strategy_id = ?"


class _Registry(StrategyRegistry):
    def __init__(self, db: Any, current: StrategyStatus) -> None:
        super().__init__(db)
        self.gets: list[str] = []
        self._record = StrategyRecord(
            strategy_id="s-9",
            name="demo",
            version="1.0.0",
            filepath="strategies/demo.py",
            status=current,
            registered_at=datetime(2026, 11, 1, tzinfo=UTC),
        )

    async def get(self, strategy_id: str) -> StrategyRecord | None:
        self.gets.append(strategy_id)
        return self._record


class _Harness:
    def __init__(self, current: StrategyStatus) -> None:
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=None)
        self.strategy_registry = _Registry(self.db, current)
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            strategy_registry=self.strategy_registry,
            audit_logger=self.audit_logger,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, args: Any) -> dict:
        return await self.server._dispatch(
            {
                "id": "req-1",
                "command": "strategy.set_status",
                "args": args,
                "actor": ACTOR,
            }
        )


@pytest.mark.asyncio
async def test_set_status_updates_the_registry_and_audits() -> None:
    harness = _Harness(StrategyStatus.REGISTERED)
    response = await harness.send({"strategy_id": "s-9", "status": "archived"})
    assert response == {
        "id": "req-1",
        "status": "ok",
        "result": {"strategy_id": "s-9", "status": "archived"},
    }
    assert harness.strategy_registry.gets == ["s-9"]
    harness.db.execute.assert_awaited_once_with(UPDATE_SQL, ("archived", "s-9"))
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="strategy.set_status",
        resource="strategy:s-9",
        detail="status=archived",
        ip="",
    )


@pytest.mark.asyncio
async def test_set_status_transition_reject_keeps_the_service_message() -> None:
    harness = _Harness(StrategyStatus.ARCHIVED)
    response = await harness.send({"strategy_id": "s-9", "status": "adopted"})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "EXECUTION_ERROR",
            "message": "전환 불가: archived → adopted (허용: )",
        },
    }
    harness.db.execute.assert_not_awaited()
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_status_outside_the_status_values() -> None:
    harness = _Harness(StrategyStatus.REGISTERED)
    response = await harness.send({"strategy_id": "s-9", "status": "bogus"})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": validation_message(
                "strategy.set_status", ("status", "literal_error")
            ),
        },
    }
    assert harness.strategy_registry.gets == []
    harness.audit_logger.log.assert_not_awaited()


def test_status_literal_is_the_strategy_status_values() -> None:
    members = typing.get_args(
        StrategySetStatusRequest.model_fields["status"].annotation
    )
    assert len(members) == len(set(members)) > 0
    assert set(members) == {status.value for status in StrategyStatus}
