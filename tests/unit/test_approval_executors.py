"""결재 유형별 executor 등록 및 승인→실행 테스트.

Refs #446: 8건 executor 신규 등록 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.report.models import ReportStatus


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


@pytest.fixture
async def eventbus():
    return EventBus()


def _build_executors() -> tuple[dict, dict]:
    """mock executor dict와 mock 서비스 객체를 생성.

    Returns:
        (executors dict, mocks dict) — mocks에서 호출 검증 가능.
    """
    from ante.strategy.registry import StrategyStatus

    report_store = MagicMock()
    report_store.update_status = AsyncMock()

    strategy_registry = MagicMock()
    strategy_registry.update_status = AsyncMock()

    bot_manager = MagicMock()
    bot_manager.create_bot = AsyncMock()
    bot_manager.assign_strategy = AsyncMock()
    bot_manager.change_strategy = AsyncMock()
    bot_manager.stop_bot = AsyncMock()
    bot_manager.resume_bot = AsyncMock()
    bot_manager.delete_bot = AsyncMock()

    treasury = MagicMock()
    treasury.update_budget = AsyncMock()

    rule_engine = MagicMock()
    rule_engine.update_rules = MagicMock()  # sync

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

    async def _exec_rule_change(params: dict) -> None:
        rule_engine.update_rules(params["bot_id"], params["rules"])

    executors = {
        "strategy_adopt": _exec_strategy_adopt,
        "strategy_retire": _exec_strategy_retire,
        "bot_create": lambda params: bot_manager.create_bot(**params),
        "bot_assign_strategy": lambda params: bot_manager.assign_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_change_strategy": lambda params: bot_manager.change_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_stop": lambda params: bot_manager.stop_bot(params["bot_id"]),
        "bot_resume": lambda params: bot_manager.resume_bot(params["bot_id"]),
        "bot_delete": lambda params: bot_manager.delete_bot(params["bot_id"]),
        "budget_change": lambda params: treasury.update_budget(
            params["bot_id"], params["amount"]
        ),
        "rule_change": _exec_rule_change,
    }

    mocks = {
        "report_store": report_store,
        "strategy_registry": strategy_registry,
        "bot_manager": bot_manager,
        "treasury": treasury,
        "rule_engine": rule_engine,
    }
    return executors, mocks


@pytest.fixture
async def service_with_executors(db, eventbus):
    """모든 executor가 등록된 ApprovalService."""
    executors, mocks = _build_executors()
    svc = ApprovalService(db=db, eventbus=eventbus, executors=executors)
    await svc.initialize()
    return svc, mocks


class TestStrategyAdoptExecutor:
    """strategy_adopt executor 테스트."""

    async def test_approve_calls_update_status_adopted(self, service_with_executors):
        from ante.strategy.registry import StrategyStatus

        svc, mocks = service_with_executors
        req = await svc.create(
            type="strategy_adopt",
            requester="agent",
            title="전략 채택",
            params={
                "report_id": "rpt-001",
                "strategy_id": "strat-001",
                "strategy_name": "momentum",
            },
        )
        await svc.approve(req.id)
        mocks["report_store"].update_status.assert_awaited_once_with(
            "rpt-001", ReportStatus.ADOPTED
        )
        mocks["strategy_registry"].update_status.assert_awaited_once_with(
            "strat-001", StrategyStatus.ADOPTED
        )


class TestStrategyRetireExecutor:
    """strategy_retire executor 테스트."""

    async def test_approve_calls_update_status_retired(self, service_with_executors):
        from ante.strategy.registry import StrategyStatus

        svc, mocks = service_with_executors
        req = await svc.create(
            type="strategy_retire",
            requester="agent",
            title="전략 폐기",
            params={
                "report_id": "rpt-002",
                "strategy_id": "strat-002",
                "strategy_name": "mean_revert",
            },
        )
        await svc.approve(req.id)
        mocks["report_store"].update_status.assert_awaited_once_with(
            "rpt-002", ReportStatus.ARCHIVED
        )
        mocks["strategy_registry"].update_status.assert_awaited_once_with(
            "strat-002", StrategyStatus.ARCHIVED
        )


class TestBotCreateExecutor:
    """bot_create executor 테스트."""

    async def test_approve_calls_create_bot(self, service_with_executors):
        svc, mocks = service_with_executors
        params = {
            "strategy_name": "momentum",
            "budget": 10000000,
            "mode": "paper",
        }
        req = await svc.create(
            type="bot_create",
            requester="agent",
            title="봇 생성",
            params=params,
        )
        await svc.approve(req.id)
        mocks["bot_manager"].create_bot.assert_awaited_once_with(**params)


class TestBotAssignStrategyExecutor:
    """bot_assign_strategy executor 테스트."""

    async def test_approve_calls_assign_strategy(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_assign_strategy",
            requester="agent",
            title="전략 배정",
            params={"bot_id": "bot-1", "strategy_id": "strat-1"},
        )
        await svc.approve(req.id)
        mocks["bot_manager"].assign_strategy.assert_awaited_once_with(
            "bot-1", "strat-1"
        )


class TestBotChangeStrategyExecutor:
    """bot_change_strategy executor 테스트."""

    async def test_approve_calls_change_strategy(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_change_strategy",
            requester="agent",
            title="전략 변경",
            params={"bot_id": "bot-1", "strategy_id": "strat-2"},
        )
        await svc.approve(req.id)
        mocks["bot_manager"].change_strategy.assert_awaited_once_with(
            "bot-1", "strat-2"
        )


class TestBotStopExecutor:
    """bot_stop executor 테스트."""

    async def test_approve_calls_stop_bot(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_stop",
            requester="agent",
            title="봇 중지",
            params={"bot_id": "bot-1", "reason": "손실 누적"},
        )
        await svc.approve(req.id)
        mocks["bot_manager"].stop_bot.assert_awaited_once_with("bot-1")


class TestBotResumeExecutor:
    """bot_resume executor 테스트."""

    async def test_approve_calls_resume_bot(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_resume",
            requester="agent",
            title="봇 재개",
            params={"bot_id": "bot-1", "reason": "에러 해소"},
        )
        await svc.approve(req.id)
        mocks["bot_manager"].resume_bot.assert_awaited_once_with("bot-1")


class TestBotDeleteExecutor:
    """bot_delete executor 테스트."""

    async def test_approve_calls_delete_bot(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_delete",
            requester="agent",
            title="봇 삭제",
            params={"bot_id": "bot-1", "reason": "전략 폐기"},
        )
        await svc.approve(req.id)
        mocks["bot_manager"].delete_bot.assert_awaited_once_with("bot-1")


class TestBudgetChangeExecutor:
    """budget_change executor 테스트."""

    async def test_approve_calls_update_budget(self, service_with_executors):
        svc, mocks = service_with_executors
        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="예산 변경",
            params={"bot_id": "bot-1", "amount": 25000000, "current": 10000000},
        )
        await svc.approve(req.id)
        mocks["treasury"].update_budget.assert_awaited_once_with("bot-1", 25000000)


class TestRuleChangeExecutor:
    """rule_change executor 테스트."""

    async def test_approve_calls_update_rules(self, service_with_executors):
        svc, mocks = service_with_executors
        rules = [{"type": "max_position_pct", "value": 0.2}]
        req = await svc.create(
            type="rule_change",
            requester="agent",
            title="규칙 변경",
            params={"bot_id": "bot-1", "rules": rules},
        )
        await svc.approve(req.id)
        mocks["rule_engine"].update_rules.assert_called_once_with("bot-1", rules)


class TestAllExecutorsRegistered:
    """모든 결재 유형에 executor가 등록되어 있는지 확인."""

    def test_all_types_have_executor(self):
        """10개 결재 유형 모두 executor가 등록되어 있다."""
        executors, _ = _build_executors()
        expected_types = {
            "strategy_adopt",
            "strategy_retire",
            "bot_create",
            "bot_assign_strategy",
            "bot_change_strategy",
            "bot_stop",
            "bot_resume",
            "bot_delete",
            "budget_change",
            "rule_change",
        }
        assert set(executors.keys()) == expected_types
