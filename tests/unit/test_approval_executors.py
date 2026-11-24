"""결재 유형별 executor 등록 및 승인→실행 테스트.

Refs #446: 8건 executor 신규 등록 검증.
Refs #2933: 실제 build_executors·build_validators 조립을 쓴다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.approval.handlers import build_executors, build_validators
from ante.approval.models import ApprovalStatus, ApprovalValidationError
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.report.models import ReportStatus


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    # Refs #1897: aiosqlite Connection 누수 차단.
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def eventbus():
    return EventBus()


def _build_deps(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, dict]:
    """실제 executor·validator 조립에 넘길 mock deps를 생성.

    Returns:
        (deps, mocks) — mocks에서 호출 검증 가능.
    """
    from ante.bot.config import BotStatus
    from ante.strategy.loader import StrategyLoader
    from ante.strategy.registry import StrategyStatus

    class FakeStrategy:
        pass

    report_store = MagicMock()
    report_store.get = AsyncMock(return_value=SimpleNamespace(report_id="rpt"))
    report_store.update_status = AsyncMock()

    strategy_registry = MagicMock()
    strategy_record = SimpleNamespace(
        strategy_id="strat-1",
        name="momentum",
        version="1.0",
        filepath="/tmp/strategy.py",
        status=StrategyStatus.ADOPTED,
    )
    strategy_registry.get = AsyncMock(return_value=strategy_record)
    strategy_registry.update_status = AsyncMock()
    strategy_loader = MagicMock(return_value=FakeStrategy)
    monkeypatch.setattr(StrategyLoader, "load", strategy_loader)

    bots = {
        "bot-1": SimpleNamespace(
            bot_id="bot-1",
            status=BotStatus.STOPPED,
            config=SimpleNamespace(account_id="acc-test"),
        )
    }
    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(side_effect=bots.get)
    bot_manager.create_bot = AsyncMock()
    bot_manager.assign_strategy = AsyncMock()
    bot_manager.change_strategy = AsyncMock()
    bot_manager.stop_bot = AsyncMock()
    bot_manager.resume_bot = AsyncMock()
    bot_manager.delete_bot = AsyncMock()

    treasury = MagicMock()
    treasury.unallocated = 100_000_000
    treasury.update_budget = AsyncMock()
    treasury_manager = MagicMock()
    treasury_manager.get = MagicMock(return_value=treasury)

    rule_engine = MagicMock()
    rule_engine.update_rules = MagicMock()  # sync
    rule_engine_manager = MagicMock()
    rule_engine_manager.get = MagicMock(return_value=rule_engine)

    position_history = MagicMock()
    position_history.get_positions_sync = MagicMock(return_value=[])

    deps = SimpleNamespace(
        report_store=report_store,
        strategy_registry=strategy_registry,
        bot_manager=bot_manager,
        treasury_manager=treasury_manager,
        rule_engine_manager=rule_engine_manager,
        position_history=position_history,
        eventbus=None,
    )
    mocks = {
        "report_store": report_store,
        "strategy_registry": strategy_registry,
        "strategy_record": strategy_record,
        "strategy_loader": strategy_loader,
        "strategy_cls": FakeStrategy,
        "bot_manager": bot_manager,
        "bots": bots,
        "treasury": treasury,
        "treasury_manager": treasury_manager,
        "rule_engine": rule_engine,
        "rule_engine_manager": rule_engine_manager,
    }
    return deps, mocks


@pytest.fixture
async def service_with_executors(db, eventbus, monkeypatch):
    """실제 executor·validator가 등록된 ApprovalService."""
    deps, mocks = _build_deps(monkeypatch)
    svc = ApprovalService(
        db=db,
        eventbus=eventbus,
        executors=build_executors(deps),
        validators=build_validators(deps),
    )
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
        from ante.bot.config import BotConfig

        svc, mocks = service_with_executors
        params = {
            "config": {
                "bot_id": "bot-new",
                "strategy_id": "strat-1",
                "name": "momentum-bot",
                "account_id": "acc-test",
                "interval_seconds": 60,
            }
        }
        req = await svc.create(
            type="bot_create",
            requester="agent",
            title="봇 생성",
            params=params,
        )
        await svc.approve(req.id)
        expected_config = BotConfig(
            bot_id="bot-new",
            strategy_id="strat-1",
            name="momentum-bot",
            account_id="acc-test",
            interval_seconds=60,
        )
        mocks["bot_manager"].create_bot.assert_awaited_once_with(
            config=expected_config,
            strategy_cls=mocks["strategy_cls"],
            source_path=Path("/tmp/strategy.py"),
        )
        mocks["strategy_registry"].get.assert_awaited_with("strat-1")
        mocks["strategy_loader"].assert_called_once_with(Path("/tmp/strategy.py"))

    async def test_create_rejects_legacy_flat_payload(self, service_with_executors):
        svc, mocks = service_with_executors
        with pytest.raises(ApprovalValidationError, match="params.config"):
            await svc.create(
                type="bot_create",
                requester="agent",
                title="봇 생성",
                params={"account_id": "acc-test", "strategy_id": "strat-1"},
            )
        mocks["bot_manager"].create_bot.assert_not_awaited()

    async def test_create_rejects_unadopted_strategy(self, service_with_executors):
        from ante.strategy.registry import StrategyStatus

        svc, mocks = service_with_executors
        mocks["strategy_record"].status = StrategyStatus.REGISTERED
        with pytest.raises(ApprovalValidationError, match="adopted"):
            await svc.create(
                type="bot_create",
                requester="agent",
                title="봇 생성",
                params={
                    "config": {
                        "bot_id": "bot-new",
                        "strategy_id": "strat-1",
                        "account_id": "acc-test",
                    }
                },
            )
        mocks["bot_manager"].create_bot.assert_not_awaited()


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

    async def test_create_rejects_missing_bot(self, service_with_executors):
        svc, mocks = service_with_executors
        with pytest.raises(ApprovalValidationError, match="봇이 존재하지 않음"):
            await svc.create(
                type="bot_assign_strategy",
                requester="agent",
                title="전략 배정",
                params={"bot_id": "bot-missing", "strategy_id": "strat-1"},
            )
        mocks["bot_manager"].assign_strategy.assert_not_awaited()

    async def test_approve_fails_when_strategy_unadopted_after_create(
        self, service_with_executors
    ):
        from ante.strategy.registry import StrategyStatus

        svc, mocks = service_with_executors
        req = await svc.create(
            type="bot_assign_strategy",
            requester="agent",
            title="전략 배정",
            params={"bot_id": "bot-1", "strategy_id": "strat-1"},
        )
        mocks["strategy_record"].status = StrategyStatus.REGISTERED
        result = await svc.approve(req.id)
        assert result.status == ApprovalStatus.EXECUTION_FAILED
        mocks["bot_manager"].assign_strategy.assert_not_awaited()


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
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 25000000,
                "current": 10000000,
            },
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
            params={"account_id": "acc-test", "bot_id": "bot-1", "rules": rules},
        )
        await svc.approve(req.id)
        mocks["rule_engine"].update_rules.assert_called_once_with("bot-1", rules)


class TestAllExecutorsRegistered:
    """모든 결재 유형에 executor가 등록되어 있는지 확인."""

    def test_all_types_have_executor(self, monkeypatch):
        """10개 결재 유형 모두 executor가 등록되어 있다."""
        deps, _ = _build_deps(monkeypatch)
        executors = build_executors(deps)
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
