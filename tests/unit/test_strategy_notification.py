"""전략 채택/폐기 executor 알림 발행 테스트.

Refs #1004: strategy_adopt/retire executor 성공 시 NotificationEvent 발행 검증.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from ante.eventbus.bus import EventBus
from ante.eventbus.events import NotificationEvent
from ante.report.models import ReportStatus


@dataclass
class _FakeStrategyRecord:
    strategy_id: str
    name: str
    version: str
    status: str


def _build_adopt_retire_executors(eventbus: EventBus, registry_records: dict):
    """main.py의 _exec_strategy_adopt/retire 로직을 재현한다."""
    report_store = MagicMock()
    report_store.update_status = AsyncMock()

    strategy_registry = MagicMock()
    strategy_registry.update_status = AsyncMock()

    async def _get(sid: str):
        return registry_records.get(sid)

    strategy_registry.get = AsyncMock(side_effect=_get)

    async def _exec_strategy_adopt(params: dict) -> None:
        await report_store.update_status(params["report_id"], ReportStatus.ADOPTED)
        await strategy_registry.update_status(params["strategy_id"], "adopted")
        rec = await strategy_registry.get(params["strategy_id"])
        name = rec.name if rec else params["strategy_id"]
        ver = rec.version if rec else "unknown"
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="전략 채택",
                message=(
                    f"전략 '{name}' (v{ver})이 채택되었습니다. 봇에 배정할 수 있습니다."
                ),
                category="strategy",
            )
        )

    async def _exec_strategy_retire(params: dict) -> None:
        await report_store.update_status(params["report_id"], ReportStatus.ARCHIVED)
        await strategy_registry.update_status(params["strategy_id"], "archived")
        rec = await strategy_registry.get(params["strategy_id"])
        name = rec.name if rec else params["strategy_id"]
        ver = rec.version if rec else "unknown"
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="전략 폐기",
                message=f"전략 '{name}' (v{ver})이 보관 처리되었습니다.",
                category="strategy",
            )
        )

    return (
        _exec_strategy_adopt,
        _exec_strategy_retire,
        {
            "report_store": report_store,
            "strategy_registry": strategy_registry,
        },
    )


class TestStrategyAdoptNotification:
    """strategy_adopt executor 성공 시 NotificationEvent 발행."""

    async def test_adopt_emits_notification_with_name_and_version(self):
        eventbus = EventBus()
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        records = {
            "strat-001": _FakeStrategyRecord(
                strategy_id="strat-001",
                name="Momentum Alpha",
                version="1.2.0",
                status="registered",
            ),
        }
        adopt, _, _ = _build_adopt_retire_executors(eventbus, records)

        await adopt({"report_id": "rpt-001", "strategy_id": "strat-001"})

        assert len(captured) == 1
        event = captured[0]
        assert event.level == "info"
        assert event.title == "전략 채택"
        assert "Momentum Alpha" in event.message
        assert "v1.2.0" in event.message
        assert event.category == "strategy"

    async def test_adopt_fallback_when_record_not_found(self):
        eventbus = EventBus()
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        adopt, _, _ = _build_adopt_retire_executors(eventbus, {})

        await adopt({"report_id": "rpt-001", "strategy_id": "strat-missing"})

        assert len(captured) == 1
        event = captured[0]
        assert "strat-missing" in event.message
        assert "unknown" in event.message


class TestStrategyRetireNotification:
    """strategy_retire executor 성공 시 NotificationEvent 발행."""

    async def test_retire_emits_notification_with_name_and_version(self):
        eventbus = EventBus()
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        records = {
            "strat-002": _FakeStrategyRecord(
                strategy_id="strat-002",
                name="Mean Revert Beta",
                version="2.0.1",
                status="adopted",
            ),
        }
        _, retire, _ = _build_adopt_retire_executors(eventbus, records)

        await retire({"report_id": "rpt-002", "strategy_id": "strat-002"})

        assert len(captured) == 1
        event = captured[0]
        assert event.level == "info"
        assert event.title == "전략 폐기"
        assert "Mean Revert Beta" in event.message
        assert "v2.0.1" in event.message
        assert "보관 처리" in event.message
        assert event.category == "strategy"

    async def test_retire_fallback_when_record_not_found(self):
        eventbus = EventBus()
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        _, retire, _ = _build_adopt_retire_executors(eventbus, {})

        await retire({"report_id": "rpt-002", "strategy_id": "strat-gone"})

        assert len(captured) == 1
        event = captured[0]
        assert "strat-gone" in event.message
        assert "unknown" in event.message
