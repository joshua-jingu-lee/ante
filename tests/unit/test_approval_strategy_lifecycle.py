"""결재 승인 시 전략 상태 전환 통합 테스트.

Refs #1001: strategy_adopt/retire executor가 ReportStore + StrategyRegistry
모두 업데이트하는지, validator가 전략 상태를 올바르게 검증하는지 확인.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.approval.models import ApprovalValidationError, ValidationResult
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.report.models import ReportStatus
from ante.strategy.registry import StrategyStatus


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


@pytest.fixture
async def eventbus():
    return EventBus()


def _make_strategy_record(strategy_id: str, status: StrategyStatus):
    """간이 StrategyRecord stub."""

    @dataclass
    class _Record:
        strategy_id: str
        status: StrategyStatus

    return _Record(strategy_id=strategy_id, status=status)


def _build_service_with_validators(db, eventbus, registry_records: dict | None = None):
    """executor + async validator가 포함된 ApprovalService를 생성한다."""
    report_store = MagicMock()
    report_store.update_status = AsyncMock()

    strategy_registry = MagicMock()
    strategy_registry.update_status = AsyncMock()

    # get()은 async — strategy_id로 record 반환
    records = registry_records or {}

    async def _get(sid: str):
        return records.get(sid)

    strategy_registry.get = AsyncMock(side_effect=_get)

    async def _exec_strategy_adopt(params: dict) -> None:
        await report_store.update_status(params["report_id"], ReportStatus.ADOPTED)
        await strategy_registry.update_status(
            params["strategy_id"], StrategyStatus.ADOPTED
        )

    async def _exec_strategy_retire(params: dict) -> None:
        await report_store.update_status(params["report_id"], ReportStatus.ARCHIVED)
        await strategy_registry.update_status(
            params["strategy_id"], StrategyStatus.ARCHIVED
        )

    executors = {
        "strategy_adopt": _exec_strategy_adopt,
        "strategy_retire": _exec_strategy_retire,
    }

    async def _validate_strategy_retire(params: dict) -> list[ValidationResult]:
        strategy_id = params.get("strategy_id", "")
        if not strategy_id:
            return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
        record = await strategy_registry.get(strategy_id)
        if record is None:
            return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
        if record.status == StrategyStatus.ARCHIVED:
            return [ValidationResult("fail", "이미 보관된 전략입니다", "system")]
        return [ValidationResult("pass", "", "system")]

    validators = {
        "strategy_retire": _validate_strategy_retire,
    }

    svc = ApprovalService(
        db=db,
        eventbus=eventbus,
        executors=executors,
        validators=validators,
    )

    mocks = {
        "report_store": report_store,
        "strategy_registry": strategy_registry,
    }
    return svc, mocks


class TestStrategyAdoptLifecycle:
    """strategy_adopt 승인 시 ReportStore + StrategyRegistry 모두 업데이트."""

    async def test_adopt_updates_both_stores(self, db, eventbus):
        svc, mocks = _build_service_with_validators(db, eventbus)
        await svc.initialize()

        req = await svc.create(
            type="strategy_adopt",
            requester="agent",
            title="전략 채택",
            params={
                "report_id": "rpt-001",
                "strategy_id": "strat-001",
            },
        )
        await svc.approve(req.id)

        mocks["report_store"].update_status.assert_awaited_once_with(
            "rpt-001", ReportStatus.ADOPTED
        )
        mocks["strategy_registry"].update_status.assert_awaited_once_with(
            "strat-001", StrategyStatus.ADOPTED
        )


class TestStrategyRetireLifecycle:
    """strategy_retire 승인 시 ReportStore + StrategyRegistry 모두 업데이트."""

    async def test_retire_updates_both_stores(self, db, eventbus):
        records = {
            "strat-002": _make_strategy_record("strat-002", StrategyStatus.ADOPTED),
        }
        svc, mocks = _build_service_with_validators(db, eventbus, records)
        await svc.initialize()

        req = await svc.create(
            type="strategy_retire",
            requester="agent",
            title="전략 폐기",
            params={
                "report_id": "rpt-002",
                "strategy_id": "strat-002",
            },
        )
        await svc.approve(req.id)

        mocks["report_store"].update_status.assert_awaited_once_with(
            "rpt-002", ReportStatus.ARCHIVED
        )
        mocks["strategy_registry"].update_status.assert_awaited_once_with(
            "strat-002", StrategyStatus.ARCHIVED
        )


class TestStrategyRetireValidator:
    """strategy_retire validator가 전략 상태를 올바르게 검증한다."""

    async def test_missing_strategy_id_fails(self, db, eventbus):
        svc, _ = _build_service_with_validators(db, eventbus)
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="strategy_id가 누락"):
            await svc.create(
                type="strategy_retire",
                requester="agent",
                title="전략 폐기",
                params={"report_id": "rpt-003"},
            )

    async def test_unknown_strategy_fails(self, db, eventbus):
        svc, _ = _build_service_with_validators(db, eventbus, registry_records={})
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="전략을 찾을 수 없습니다"):
            await svc.create(
                type="strategy_retire",
                requester="agent",
                title="전략 폐기",
                params={
                    "report_id": "rpt-003",
                    "strategy_id": "strat-nonexist",
                },
            )

    async def test_already_archived_fails(self, db, eventbus):
        records = {
            "strat-archived": _make_strategy_record(
                "strat-archived", StrategyStatus.ARCHIVED
            ),
        }
        svc, _ = _build_service_with_validators(db, eventbus, records)
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="이미 보관된 전략"):
            await svc.create(
                type="strategy_retire",
                requester="agent",
                title="전략 폐기",
                params={
                    "report_id": "rpt-004",
                    "strategy_id": "strat-archived",
                },
            )

    async def test_adopted_strategy_passes_validation(self, db, eventbus):
        records = {
            "strat-adopted": _make_strategy_record(
                "strat-adopted", StrategyStatus.ADOPTED
            ),
        }
        svc, _ = _build_service_with_validators(db, eventbus, records)
        await svc.initialize()

        req = await svc.create(
            type="strategy_retire",
            requester="agent",
            title="전략 폐기",
            params={
                "report_id": "rpt-005",
                "strategy_id": "strat-adopted",
            },
        )
        assert req.status.value == "pending"
