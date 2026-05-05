"""AutoApproveEvaluator 및 전결 연동 단위 테스트."""

from __future__ import annotations

import pytest

from ante.account.models import Account, TradingMode
from ante.approval.auto_approve import (
    EXCLUDED_TYPES,
    AutoApproveConfig,
    AutoApproveEvaluator,
)
from ante.approval.models import ApprovalStatus
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalCreatedEvent, ApprovalResolvedEvent

# ── Fixtures ─────────────────────────────────────────


def _account(account_id: str, trading_mode: TradingMode) -> Account:
    return Account(
        account_id=account_id,
        name=account_id,
        exchange="KRX",
        currency="KRW",
        trading_mode=trading_mode,
    )


@pytest.fixture
def accounts() -> dict[str, Account]:
    return {
        "virtual-acc": _account("virtual-acc", TradingMode.VIRTUAL),
        "live-acc": _account("live-acc", TradingMode.LIVE),
    }


@pytest.fixture
def account_resolver(accounts):
    async def resolve(account_id: str) -> Account | None:
        return accounts.get(account_id)

    return resolve


@pytest.fixture
def enabled_config() -> AutoApproveConfig:
    """전결 활성화 설정."""
    return AutoApproveConfig(
        enabled=True,
        bot_stop=True,
        bot_create_virtual=True,
        budget_change_max=5_000_000,
    )


@pytest.fixture
def disabled_config() -> AutoApproveConfig:
    """전결 비활성화 설정."""
    return AutoApproveConfig(enabled=False)


@pytest.fixture
def evaluator(
    enabled_config: AutoApproveConfig, account_resolver
) -> AutoApproveEvaluator:
    return AutoApproveEvaluator(
        config=enabled_config,
        account_resolver=account_resolver,
    )


@pytest.fixture
def disabled_evaluator(disabled_config: AutoApproveConfig) -> AutoApproveEvaluator:
    return AutoApproveEvaluator(config=disabled_config)


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    return database


@pytest.fixture
async def eventbus():
    return EventBus()


@pytest.fixture
async def service_with_auto_approve(db, eventbus, enabled_config):
    """전결 활성화된 ApprovalService."""
    executed = []

    async def mock_executor(params: dict) -> None:
        executed.append(params)

    async def resolve_account(account_id: str) -> Account | None:
        accounts = {
            "virtual-acc": _account("virtual-acc", TradingMode.VIRTUAL),
            "live-acc": _account("live-acc", TradingMode.LIVE),
        }
        return accounts.get(account_id)

    evaluator = AutoApproveEvaluator(
        config=enabled_config,
        account_resolver=resolve_account,
    )
    svc = ApprovalService(
        db=db,
        eventbus=eventbus,
        executors={"bot_stop": mock_executor, "bot_create": mock_executor},
        auto_approve_evaluator=evaluator,
    )
    await svc.initialize()
    return svc, executed


@pytest.fixture
async def service_without_auto_approve(db, eventbus):
    """전결 비활성화된 ApprovalService (기본)."""
    svc = ApprovalService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


# ── AutoApproveConfig ────────────────────────────────


class TestAutoApproveConfig:
    def test_default_config(self):
        """기본 설정: 비활성화."""
        config = AutoApproveConfig()
        assert config.enabled is False
        assert config.bot_stop is True
        assert config.bot_create_virtual is True
        assert config.budget_change_max == 5_000_000

    def test_from_dict(self):
        """dict에서 설정 생성."""
        data = {
            "enabled": True,
            "rules": {
                "bot_stop": True,
                "bot_create_virtual": False,
                "budget_change_max": 3000000,
            },
        }
        config = AutoApproveConfig.from_dict(data)
        assert config.enabled is True
        assert config.bot_stop is True
        assert config.bot_create_virtual is False
        assert config.budget_change_max == 3_000_000

    def test_from_dict_empty(self):
        """빈 dict에서 기본값 적용."""
        config = AutoApproveConfig.from_dict({})
        assert config.enabled is False
        assert config.bot_stop is True

    def test_from_dict_missing_rules(self):
        """rules 키 없이 enabled만 있는 경우."""
        config = AutoApproveConfig.from_dict({"enabled": True})
        assert config.enabled is True
        assert config.bot_stop is True
        assert config.budget_change_max == 5_000_000


# ── AutoApproveEvaluator ─────────────────────────────


class TestAutoApproveEvaluator:
    async def test_disabled_returns_false(self, disabled_evaluator):
        """비활성화 시 항상 False."""
        assert await disabled_evaluator.should_auto_approve("bot_stop") is False
        assert await disabled_evaluator.should_auto_approve("budget_change") is False

    async def test_bot_stop_auto_approved(self, evaluator):
        """bot_stop은 자동 승인."""
        assert (
            await evaluator.should_auto_approve("bot_stop", {"bot_id": "bot-1"}) is True
        )

    async def test_bot_create_virtual_account_auto_approved(self, evaluator):
        """virtual Account 봇 생성은 자동 승인."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "virtual-acc", "strategy_name": "test"},
            )
            is True
        )

    async def test_bot_create_live_account_not_auto_approved(self, evaluator):
        """live Account 봇 생성은 자동 승인 안 됨."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "live-acc", "strategy_name": "test"},
            )
            is False
        )

    async def test_bot_create_no_account_not_auto_approved(self, evaluator):
        """account_id 없는 봇 생성은 자동 승인 안 됨."""
        assert (
            await evaluator.should_auto_approve("bot_create", {"strategy_name": "test"})
            is False
        )

    async def test_bot_create_config_account_id_first(self, evaluator):
        """config.account_id가 flat account_id보다 우선한다."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {
                    "config": {
                        "account_id": "virtual-acc",
                        "strategy_id": "s1",
                    },
                    "account_id": "live-acc",
                },
            )
            is True
        )

    async def test_bot_create_flat_account_id_fallback(self, evaluator):
        """flat account_id도 resolver 입력으로 사용한다."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "virtual-acc", "strategy_id": "s1"},
            )
            is True
        )

    async def test_bot_create_missing_account_not_auto_approved(self, evaluator):
        """Account 조회 실패 시 자동 승인하지 않는다."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "missing-acc", "strategy_id": "s1"},
            )
            is False
        )

    async def test_bot_create_mode_value_is_ignored(self, evaluator):
        """mode 값만으로는 자동 승인하지 않는다."""
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "live-acc", "mode": "virtual", "strategy_id": "s1"},
            )
            is False
        )

    async def test_bot_create_without_resolver_not_auto_approved(self, enabled_config):
        """Account resolver가 없으면 bot_create를 자동 승인하지 않는다."""
        evaluator = AutoApproveEvaluator(config=enabled_config)
        assert (
            await evaluator.should_auto_approve(
                "bot_create",
                {"account_id": "virtual-acc", "strategy_id": "s1"},
            )
            is False
        )

    async def test_budget_change_within_limit(self, evaluator):
        """예산 변경이 한도 이내이면 자동 승인."""
        assert (
            await evaluator.should_auto_approve(
                "budget_change",
                {"bot_id": "bot-1", "amount": 15000000, "current": 10000000},
            )
            is True
        )

    async def test_budget_change_at_limit(self, evaluator):
        """예산 변경이 정확히 한도이면 자동 승인."""
        assert (
            await evaluator.should_auto_approve(
                "budget_change",
                {"bot_id": "bot-1", "amount": 15000000, "current": 10000000},
            )
            is True
        )

    async def test_budget_change_over_limit(self, evaluator):
        """예산 변경이 한도 초과이면 자동 승인 안 됨."""
        assert (
            await evaluator.should_auto_approve(
                "budget_change",
                {"bot_id": "bot-1", "amount": 20000000, "current": 10000000},
            )
            is False
        )

    async def test_budget_change_decrease_within_limit(self, evaluator):
        """예산 감액도 변경액 기준으로 평가."""
        assert (
            await evaluator.should_auto_approve(
                "budget_change",
                {"bot_id": "bot-1", "amount": 7000000, "current": 10000000},
            )
            is True
        )

    async def test_strategy_adopt_excluded(self, evaluator):
        """strategy_adopt는 전결 대상에서 제외."""
        assert (
            await evaluator.should_auto_approve(
                "strategy_adopt", {"strategy_name": "test", "report_id": "r1"}
            )
            is False
        )

    async def test_strategy_retire_excluded(self, evaluator):
        """strategy_retire는 전결 대상에서 제외."""
        assert (
            await evaluator.should_auto_approve(
                "strategy_retire", {"strategy_name": "test", "report_id": "r1"}
            )
            is False
        )

    def test_excluded_types_constant(self):
        """제외 유형 상수 확인."""
        assert "strategy_adopt" in EXCLUDED_TYPES
        assert "strategy_retire" in EXCLUDED_TYPES

    async def test_unknown_type_not_auto_approved(self, evaluator):
        """알 수 없는 유형은 자동 승인 안 됨."""
        assert await evaluator.should_auto_approve("unknown_type") is False

    async def test_rule_change_not_auto_approved(self, evaluator):
        """rule_change는 전결 규칙에 없으므로 자동 승인 안 됨."""
        assert (
            await evaluator.should_auto_approve("rule_change", {"bot_id": "bot-1"})
            is False
        )

    async def test_bot_stop_disabled_in_config(self):
        """bot_stop 규칙이 비활성화된 경우."""
        config = AutoApproveConfig(enabled=True, bot_stop=False)
        ev = AutoApproveEvaluator(config=config)
        assert await ev.should_auto_approve("bot_stop", {"bot_id": "bot-1"}) is False

    async def test_budget_change_max_zero_disables(self):
        """budget_change_max가 0이면 예산 변경 전결 비활성화."""
        config = AutoApproveConfig(enabled=True, budget_change_max=0)
        ev = AutoApproveEvaluator(config=config)
        assert (
            await ev.should_auto_approve(
                "budget_change",
                {"bot_id": "bot-1", "amount": 10000000, "current": 10000000},
            )
            is False
        )


# ── ApprovalService 전결 연동 ─────────────────────────


class TestServiceAutoApprove:
    async def test_auto_approve_creates_approved_request(
        self, service_with_auto_approve
    ):
        """전결 조건 충족 시 approved 상태로 생성."""
        svc, _executed = service_with_auto_approve
        req = await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        assert req.status == ApprovalStatus.APPROVED
        assert req.resolved_by == "system:auto_approve"
        assert req.resolved_at != ""
        # history: created + approved + executed
        assert len(req.history) == 3
        assert req.history[0]["action"] == "created"
        assert req.history[1]["action"] == "approved"
        assert req.history[1]["actor"] == "system:auto_approve"
        assert req.history[2]["action"] == "executed"

    async def test_auto_approve_executes_handler(self, service_with_auto_approve):
        """전결 시 executor가 실행된다."""
        svc, executed = service_with_auto_approve
        await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        assert len(executed) == 1
        assert executed[0]["bot_id"] == "bot-1"

    async def test_bot_create_virtual_account_auto_approved_by_service(
        self, service_with_auto_approve
    ):
        """bot_create는 virtual Account 기준으로 자동 승인된다."""
        svc, executed = service_with_auto_approve
        req = await svc.create(
            type="bot_create",
            requester="agent:dev",
            title="봇 생성 요청",
            params={"account_id": "virtual-acc", "strategy_id": "s1"},
        )

        assert req.status == ApprovalStatus.APPROVED
        assert req.resolved_by == "system:auto_approve"
        assert len(executed) == 1
        assert executed[0]["account_id"] == "virtual-acc"

    async def test_bot_create_live_account_stays_pending_by_service(
        self, service_with_auto_approve
    ):
        """bot_create live Account는 자동 승인되지 않는다."""
        svc, executed = service_with_auto_approve
        req = await svc.create(
            type="bot_create",
            requester="agent:dev",
            title="봇 생성 요청",
            params={"account_id": "live-acc", "strategy_id": "s1"},
        )

        assert req.status == ApprovalStatus.PENDING
        assert req.resolved_by == ""
        assert len(executed) == 0

    async def test_auto_approve_publishes_created_event_with_flag(
        self, service_with_auto_approve, eventbus
    ):
        """전결 시 ApprovalCreatedEvent에 auto_approved=True."""
        svc, _executed = service_with_auto_approve
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalCreatedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalCreatedEvent, handler)

        await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        assert len(received) == 1
        assert received[0].auto_approved is True

    async def test_auto_approve_publishes_resolved_event(
        self, service_with_auto_approve, eventbus
    ):
        """전결 시 ApprovalResolvedEvent도 발행된다."""
        svc, _executed = service_with_auto_approve
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalResolvedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, handler)

        await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        assert len(received) == 1
        assert received[0].resolution == "approved"
        assert received[0].resolved_by == "system:auto_approve"

    async def test_non_matching_request_stays_pending(self, service_with_auto_approve):
        """전결 조건 미충족 시 pending 상태 유지."""
        svc, executed = service_with_auto_approve
        req = await svc.create(
            type="budget_change",
            requester="agent:dev",
            title="예산 대폭 증액",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 100000000,
                "current": 10000000,
            },
        )

        assert req.status == ApprovalStatus.PENDING
        assert req.resolved_by == ""
        assert len(executed) == 0

    async def test_disabled_auto_approve_stays_pending(
        self, service_without_auto_approve
    ):
        """전결 비활성화 시 항상 pending."""
        svc = service_without_auto_approve
        req = await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        assert req.status == ApprovalStatus.PENDING

    async def test_auto_approve_persisted_in_db(self, service_with_auto_approve):
        """전결 결과가 DB에 영속화."""
        svc, _executed = service_with_auto_approve
        req = await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
            params={"bot_id": "bot-1"},
        )

        fetched = await svc.get(req.id)
        assert fetched is not None
        assert fetched.status == "approved"
        assert fetched.resolved_by == "system:auto_approve"
        assert len(fetched.history) == 3

    async def test_created_event_auto_approved_false_for_normal(
        self, service_without_auto_approve, eventbus
    ):
        """일반 요청의 ApprovalCreatedEvent에 auto_approved=False."""
        svc = service_without_auto_approve
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalCreatedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalCreatedEvent, handler)

        await svc.create(
            type="bot_stop",
            requester="agent:dev",
            title="봇 중지 요청",
        )

        assert len(received) == 1
        assert received[0].auto_approved is False

    async def test_strategy_adopt_never_auto_approved(self, service_with_auto_approve):
        """strategy_adopt는 전결 활성화되어도 자동 승인 안 됨."""
        svc, _executed = service_with_auto_approve
        req = await svc.create(
            type="strategy_adopt",
            requester="agent:dev",
            title="전략 채택 요청",
            params={"strategy_name": "test", "report_id": "r1"},
        )

        assert req.status == ApprovalStatus.PENDING

    async def test_strategy_retire_never_auto_approved(self, service_with_auto_approve):
        """strategy_retire는 전결 활성화되어도 자동 승인 안 됨."""
        svc, _executed = service_with_auto_approve
        req = await svc.create(
            type="strategy_retire",
            requester="agent:dev",
            title="전략 폐기 요청",
            params={"strategy_name": "test", "report_id": "r1"},
        )

        assert req.status == ApprovalStatus.PENDING
