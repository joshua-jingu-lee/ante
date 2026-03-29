"""strategy_adopt 검증기 단위 테스트.

Refs #1082: params 누락 시 fail 리뷰를 반환하여 결재 생성 차단.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.approval.models import ApprovalValidationError, ValidationResult
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


@pytest.fixture
async def eventbus():
    return EventBus()


def _make_validator(strategy_exists: bool = True):
    """_validate_strategy_adopt 와 동일한 로직의 검증기를 생성한다.

    main.py 내부 클로저를 직접 import 할 수 없으므로 동일 로직을 재현한다.
    """
    strategy_registry = MagicMock()
    if strategy_exists:
        record = MagicMock()
        strategy_registry.get = AsyncMock(return_value=record)
    else:
        strategy_registry.get = AsyncMock(return_value=None)

    async def _validate_strategy_adopt(params: dict) -> list[ValidationResult]:
        strategy_id = params.get("strategy_id", "")
        if not strategy_id:
            return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
        report_id = params.get("report_id", "")
        if not report_id:
            return [ValidationResult("fail", "report_id가 누락되었습니다", "system")]
        record = await strategy_registry.get(strategy_id)
        if record is None:
            return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
        return [ValidationResult("pass", "", "system")]

    return _validate_strategy_adopt


class TestValidateStrategyAdopt:
    """strategy_adopt 검증기 테스트."""

    async def test_empty_params_fails(self):
        """빈 params는 strategy_id 누락으로 fail."""
        validator = _make_validator()
        results = await validator({})
        assert len(results) == 1
        assert results[0].grade == "fail"
        assert "strategy_id" in results[0].detail

    async def test_missing_report_id_fails(self):
        """strategy_id만 있고 report_id 누락 시 fail."""
        validator = _make_validator()
        results = await validator({"strategy_id": "strat-1"})
        assert len(results) == 1
        assert results[0].grade == "fail"
        assert "report_id" in results[0].detail

    async def test_missing_strategy_id_fails(self):
        """report_id만 있고 strategy_id 누락 시 fail."""
        validator = _make_validator()
        results = await validator({"report_id": "rpt-1"})
        assert len(results) == 1
        assert results[0].grade == "fail"
        assert "strategy_id" in results[0].detail

    async def test_valid_params_pass(self):
        """유효한 params는 pass."""
        validator = _make_validator(strategy_exists=True)
        results = await validator({"strategy_id": "strat-1", "report_id": "rpt-1"})
        assert len(results) == 1
        assert results[0].grade == "pass"

    async def test_nonexistent_strategy_fails(self):
        """전략이 존재하지 않으면 fail."""
        validator = _make_validator(strategy_exists=False)
        results = await validator(
            {"strategy_id": "strat-unknown", "report_id": "rpt-1"}
        )
        assert len(results) == 1
        assert results[0].grade == "fail"
        assert "찾을 수 없" in results[0].detail


class TestServiceRejectsInvalidStrategyAdopt:
    """ApprovalService에 검증기를 등록하면 빈 params로 생성이 거부되는지 테스트."""

    async def test_create_with_empty_params_raises(self, db, eventbus):
        """빈 params로 strategy_adopt 결재 생성 시 ApprovalValidationError."""
        validator = _make_validator()
        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"strategy_adopt": validator},
        )
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="strategy_id"):
            await svc.create(
                type="strategy_adopt",
                requester="agent",
                title="테스트",
                params={},
            )
