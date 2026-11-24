"""#2692: 결재 실행기·사전 검증기의 특성 테스트.

처리기는 실제 ``_init_approval(s)`` 가 ``ApprovalService`` 에 등록한 사전에서
결재 유형 문자열로만 꺼낸다. 서비스는 호출을 하나의 목록에 기록하는 대역이다.
기대값은 지금 동작 그대로의 리터럴이다(#2900 의 동작과 #2582 의 채택 검증 포함).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.approval.models import ValidationResult
from ante.bot.config import BotConfig, BotStatus
from ante.bot.exceptions import BotStateConflict
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import NotificationEvent
from ante.main import Services, _init_approval

EXECUTOR_KEYS = [
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
]

VALIDATOR_KEYS = [
    "strategy_adopt",
    "strategy_retire",
    "bot_create",
    "bot_delete",
    "bot_change_strategy",
    "bot_assign_strategy",
    "bot_resume",
    "budget_change",
]

EXECUTOR_IS_COROUTINE_FUNCTION = {
    "strategy_adopt": True,
    "strategy_retire": True,
    "bot_create": True,
    "bot_assign_strategy": True,
    "bot_change_strategy": True,
    "bot_stop": True,
    "bot_resume": False,
    "bot_delete": False,
    "budget_change": True,
    "rule_change": True,
}

VALIDATOR_IS_COROUTINE_FUNCTION = {
    "strategy_adopt": True,
    "strategy_retire": True,
    "bot_create": True,
    "bot_delete": False,
    "bot_change_strategy": True,
    "bot_assign_strategy": True,
    "bot_resume": False,
    "budget_change": False,
}


class _Log:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def add(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))


class _ReportStore:
    def __init__(self, log: _Log) -> None:
        self._log = log

    async def update_status(self, report_id: Any, status: Any) -> None:
        self._log.add("report_store.update_status", report_id, str(status))

    async def get(self, report_id: Any) -> Any:
        self._log.add("report_store.get", report_id)
        return SimpleNamespace(report_id=report_id) if report_id == "r-1" else None


class _StrategyRegistry:
    def __init__(self, log: _Log, records: dict[str, Any]) -> None:
        self._log = log
        self.records = records

    async def update_status(self, strategy_id: Any, status: Any) -> None:
        self._log.add("strategy_registry.update_status", strategy_id, str(status))

    async def get(self, strategy_id: Any) -> Any:
        self._log.add("strategy_registry.get", strategy_id)
        return self.records.get(strategy_id)


class _BotManager:
    def __init__(self, log: _Log, bots: dict[str, Any], tag: str = "bot_manager"):
        self._log = log
        self.bots = bots
        self.tag = tag
        self.stop_error: BaseException | None = None

    def get_bot(self, bot_id: Any) -> Any:
        self._log.add(f"{self.tag}.get_bot", bot_id)
        return self.bots.get(bot_id)

    async def create_bot(self, **kwargs: Any) -> None:
        self._log.add(f"{self.tag}.create_bot", **kwargs)

    async def stop_bot(self, bot_id: Any) -> None:
        self._log.add(f"{self.tag}.stop_bot", bot_id)
        if self.stop_error is not None:
            raise self.stop_error

    async def assign_strategy(self, bot_id: Any, strategy_id: Any) -> None:
        self._log.add(f"{self.tag}.assign_strategy", bot_id, strategy_id)

    async def change_strategy(self, bot_id: Any, strategy_id: Any) -> None:
        self._log.add(f"{self.tag}.change_strategy", bot_id, strategy_id)

    async def resume_bot(self, bot_id: Any) -> None:
        self._log.add(f"{self.tag}.resume_bot", bot_id)

    async def delete_bot(self, bot_id: Any) -> None:
        self._log.add(f"{self.tag}.delete_bot", bot_id)


class _Treasury:
    def __init__(self, log: _Log, unallocated: float) -> None:
        self._log = log
        self.unallocated = unallocated

    async def update_budget(self, bot_id: Any, amount: Any) -> None:
        self._log.add("treasury.update_budget", bot_id, amount)


class _TreasuryManager:
    def __init__(self, log: _Log, treasuries: dict[str, _Treasury]) -> None:
        self._log = log
        self.treasuries = treasuries

    def get(self, account_id: Any) -> _Treasury:
        self._log.add("treasury_manager.get", account_id)
        return self.treasuries[account_id]


class _RuleEngine:
    def __init__(self, log: _Log) -> None:
        self._log = log

    def update_rules(self, bot_id: Any, rules: Any) -> None:
        self._log.add("rule_engine.update_rules", bot_id, rules)


class _RuleEngineManager:
    def __init__(self, log: _Log) -> None:
        self._log = log

    def get(self, account_id: Any) -> _RuleEngine:
        self._log.add("rule_engine_manager.get", account_id)
        return _RuleEngine(self._log)


class _PositionHistory:
    def __init__(self, log: _Log, positions: dict[str, list[Any]]) -> None:
        self._log = log
        self.positions = positions

    def get_positions_sync(self, bot_id: Any, *, account_id: Any = None) -> list[Any]:
        self._log.add(
            "position_history.get_positions_sync", bot_id, account_id=account_id
        )
        return list(self.positions.get(bot_id, []))


def _bot(bot_id: str, status: BotStatus, account_id: str = "acc-a") -> Any:
    return SimpleNamespace(
        bot_id=bot_id,
        status=status,
        config=BotConfig(
            bot_id=bot_id, strategy_id="s-old", name=bot_id, account_id=account_id
        ),
    )


def _record(status: str, name: str = "Momo", version: str = "1.2") -> Any:
    return SimpleNamespace(
        name=name, version=version, status=status, filepath="/strategies/momo.py"
    )


class _Env:
    def __init__(self, s: Services, log: _Log, events: list[NotificationEvent]):
        self.s = s
        self.log = log
        self.events = events

    def executor(self, approval_type: str) -> Any:
        return self.s.approval_service._executors[approval_type]

    def validator(self, approval_type: str) -> Any:
        return self.s.approval_service._validators[approval_type]


@pytest.fixture
async def env(tmp_path: Path) -> Any:
    db = Database(str(tmp_path / "approval.db"))
    await db.connect()
    log = _Log()
    eventbus = EventBus()
    events: list[NotificationEvent] = []

    async def _on_notification(event: NotificationEvent) -> None:
        log.add(
            "eventbus.publish", event.level, event.title, event.message, event.category
        )
        events.append(event)

    eventbus.subscribe(NotificationEvent, _on_notification)

    s = Services()
    s.db = db
    s.eventbus = eventbus
    s.config = SimpleNamespace(get=lambda key, default=None: {})
    s.account_service = None
    s.report_store = _ReportStore(log)
    s.strategy_registry = _StrategyRegistry(
        log,
        {
            "s-adopted": _record("adopted"),
            "s-registered": _record("registered"),
            "s-archived": _record("archived"),
        },
    )
    s.bot_manager = _BotManager(
        log,
        {
            "b-stopped": _bot("b-stopped", BotStatus.STOPPED),
            "b-error": _bot("b-error", BotStatus.ERROR),
            "b-running": _bot("b-running", BotStatus.RUNNING),
        },
    )
    s.treasury_manager = _TreasuryManager(
        log, {"acc-a": _Treasury(log, unallocated=1000.0)}
    )
    s.rule_engine_manager = _RuleEngineManager(log)
    s.position_history = _PositionHistory(log, {"b-stopped-pos": [object()]})
    await _init_approval(s)
    try:
        yield _Env(s, log, events)
    finally:
        if s.approval_expire_task is not None:
            s.approval_expire_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await s.approval_expire_task
        await db.close()


def _vr(results: list[ValidationResult]) -> list[tuple[str, str, str]]:
    return [(r.grade, r.detail, r.reviewer) for r in results]


async def _validate(env: _Env, approval_type: str, params: dict[str, Any]) -> Any:
    result = env.validator(approval_type)(params)
    if inspect.isawaitable(result):
        result = await result
    return _vr(result)


class TestRegistration:
    async def test_executor_keys_in_order(self, env: _Env) -> None:
        assert list(env.s.approval_service._executors) == EXECUTOR_KEYS

    async def test_validator_keys_in_order(self, env: _Env) -> None:
        assert list(env.s.approval_service._validators) == VALIDATOR_KEYS

    async def test_executor_shapes(self, env: _Env) -> None:
        shapes = {
            key: inspect.iscoroutinefunction(fn)
            for key, fn in env.s.approval_service._executors.items()
        }
        assert shapes == EXECUTOR_IS_COROUTINE_FUNCTION

    async def test_validator_shapes(self, env: _Env) -> None:
        shapes = {
            key: inspect.iscoroutinefunction(fn)
            for key, fn in env.s.approval_service._validators.items()
        }
        assert shapes == VALIDATOR_IS_COROUTINE_FUNCTION


class TestStrategyExecutors:
    async def test_adopt_with_record_issue_2900(self, env: _Env) -> None:
        await env.executor("strategy_adopt")(
            {"report_id": "r-1", "strategy_id": "s-adopted"}
        )
        assert env.log.calls == [
            ("report_store.update_status", ("r-1", "adopted"), {}),
            ("strategy_registry.update_status", ("s-adopted", "adopted"), {}),
            ("strategy_registry.get", ("s-adopted",), {}),
            (
                "eventbus.publish",
                (
                    "info",
                    "전략 채택",
                    "전략 'Momo' (v1.2)이 채택되었습니다. 봇에 배정할 수 있습니다.",
                    "strategy",
                ),
                {},
            ),
        ]

    async def test_adopt_without_record_issue_2900(self, env: _Env) -> None:
        await env.executor("strategy_adopt")({"report_id": "r-1", "strategy_id": "s-x"})
        assert env.log.calls == [
            ("report_store.update_status", ("r-1", "adopted"), {}),
            ("strategy_registry.update_status", ("s-x", "adopted"), {}),
            ("strategy_registry.get", ("s-x",), {}),
            (
                "eventbus.publish",
                (
                    "info",
                    "전략 채택",
                    "전략 's-x' (vunknown)이 채택되었습니다. 봇에 배정할 수 있습니다.",
                    "strategy",
                ),
                {},
            ),
        ]

    async def test_adopt_without_eventbus_publishes_nothing(self, env: _Env) -> None:
        env.s.eventbus = None
        await env.executor("strategy_adopt")(
            {"report_id": "r-1", "strategy_id": "s-adopted"}
        )
        assert env.log.calls == [
            ("report_store.update_status", ("r-1", "adopted"), {}),
            ("strategy_registry.update_status", ("s-adopted", "adopted"), {}),
            ("strategy_registry.get", ("s-adopted",), {}),
        ]

    async def test_adopt_missing_report_id_raises_before_any_call_issue_2900(
        self, env: _Env
    ) -> None:
        with pytest.raises(KeyError) as ei:
            await env.executor("strategy_adopt")({"strategy_id": "s-adopted"})
        assert ei.value.args == ("report_id",)
        assert env.log.calls == []

    async def test_retire_with_record_issue_2900(self, env: _Env) -> None:
        await env.executor("strategy_retire")(
            {"report_id": "r-2", "strategy_id": "s-adopted"}
        )
        assert env.log.calls == [
            ("report_store.update_status", ("r-2", "archived"), {}),
            ("strategy_registry.update_status", ("s-adopted", "archived"), {}),
            ("strategy_registry.get", ("s-adopted",), {}),
            (
                "eventbus.publish",
                (
                    "info",
                    "전략 폐기",
                    "전략 'Momo' (v1.2)이 보관 처리되었습니다.",
                    "strategy",
                ),
                {},
            ),
        ]

    async def test_retire_without_record_issue_2900(self, env: _Env) -> None:
        await env.executor("strategy_retire")(
            {"report_id": "r-2", "strategy_id": "s-x"}
        )
        assert env.log.calls == [
            ("report_store.update_status", ("r-2", "archived"), {}),
            ("strategy_registry.update_status", ("s-x", "archived"), {}),
            ("strategy_registry.get", ("s-x",), {}),
            (
                "eventbus.publish",
                (
                    "info",
                    "전략 폐기",
                    "전략 's-x' (vunknown)이 보관 처리되었습니다.",
                    "strategy",
                ),
                {},
            ),
        ]

    async def test_retire_missing_report_id_raises_before_any_call_issue_2900(
        self, env: _Env
    ) -> None:
        with pytest.raises(KeyError) as ei:
            await env.executor("strategy_retire")({"strategy_id": "s-adopted"})
        assert ei.value.args == ("report_id",)
        assert env.log.calls == []


class TestBotCreateExecutor:
    @pytest.fixture(autouse=True)
    def _loader(self, monkeypatch: pytest.MonkeyPatch, env: _Env) -> None:
        def _load(filepath: Path) -> Any:
            env.log.add("StrategyLoader.load", filepath)
            return "StrategyClass"

        monkeypatch.setattr(
            "ante.strategy.loader.StrategyLoader.load", staticmethod(_load)
        )

    @staticmethod
    def _params(strategy_id: str) -> dict[str, Any]:
        return {
            "config": {
                "bot_id": "b-new",
                "strategy_id": strategy_id,
                "account_id": "acc-a",
                "interval_seconds": 30,
            }
        }

    async def test_adopted_creates_bot(self, env: _Env) -> None:
        await env.executor("bot_create")(self._params("s-adopted"))
        assert env.log.calls == [
            ("strategy_registry.get", ("s-adopted",), {}),
            ("StrategyLoader.load", (Path("/strategies/momo.py"),), {}),
            (
                "bot_manager.create_bot",
                (),
                {
                    "config": BotConfig(
                        bot_id="b-new",
                        strategy_id="s-adopted",
                        name="b-new",
                        account_id="acc-a",
                        interval_seconds=30,
                    ),
                    "strategy_cls": "StrategyClass",
                    "source_path": Path("/strategies/momo.py"),
                },
            ),
        ]

    async def test_missing_record_raises(self, env: _Env) -> None:
        with pytest.raises(ValueError) as ei:
            await env.executor("bot_create")(self._params("s-x"))
        assert str(ei.value) == "전략을 찾을 수 없습니다: s-x"
        assert env.log.calls == [("strategy_registry.get", ("s-x",), {})]

    async def test_registered_record_raises(self, env: _Env) -> None:
        with pytest.raises(ValueError) as ei:
            await env.executor("bot_create")(self._params("s-registered"))
        assert str(ei.value) == (
            "전략이 adopted 상태가 아닙니다: s-registered (registered)"
        )
        assert env.log.calls == [("strategy_registry.get", ("s-registered",), {})]

    async def test_missing_config_raises_before_any_call(self, env: _Env) -> None:
        with pytest.raises(ValueError) as ei:
            await env.executor("bot_create")({})
        assert str(ei.value) == "bot_create params.config가 누락되었습니다"
        assert env.log.calls == []

    async def test_invalid_account_raises_before_any_call(self, env: _Env) -> None:
        params = self._params("s-adopted")
        params["config"]["account_id"] = "default"
        with pytest.raises(InvalidAccountIdError) as ei:
            await env.executor("bot_create")(params)
        assert str(ei.value) == (
            "(approval.bot_create.config) 유효한 account_id가 필요합니다: 'default'. "
            "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다."
        )
        assert env.log.calls == []


class TestBotExecutors:
    async def test_stop_calls_stop_bot(self, env: _Env) -> None:
        assert await env.executor("bot_stop")({"bot_id": "b-running"}) is None
        assert env.log.calls == [("bot_manager.stop_bot", ("b-running",), {})]

    async def test_stop_swallows_state_conflict(self, env: _Env) -> None:
        env.s.bot_manager.stop_error = BotStateConflict("already stopped")
        assert await env.executor("bot_stop")({"bot_id": "b-stopped"}) is None
        assert env.log.calls == [("bot_manager.stop_bot", ("b-stopped",), {})]

    async def test_stop_propagates_other_errors(self, env: _Env) -> None:
        env.s.bot_manager.stop_error = RuntimeError("boom")
        with pytest.raises(RuntimeError) as ei:
            await env.executor("bot_stop")({"bot_id": "b-stopped"})
        assert str(ei.value) == "boom"
        assert env.log.calls == [("bot_manager.stop_bot", ("b-stopped",), {})]

    @pytest.mark.parametrize(
        ("approval_type", "params", "expected"),
        [
            (
                "bot_resume",
                {"bot_id": "b-3", "strategy_id": "s-3"},
                ("bot_manager.resume_bot", ("b-3",), {}),
            ),
            (
                "bot_delete",
                {"bot_id": "b-4", "strategy_id": "s-4"},
                ("bot_manager.delete_bot", ("b-4",), {}),
            ),
        ],
    )
    async def test_lambda_executors_return_coroutine(
        self, env: _Env, approval_type: str, params: dict[str, Any], expected: Any
    ) -> None:
        result = env.executor(approval_type)(params)
        assert inspect.iscoroutine(result)
        assert env.log.calls == []
        assert await result is None
        assert env.log.calls == [expected]


@pytest.mark.parametrize(
    ("approval_type", "manager_call"),
    [
        ("bot_assign_strategy", "bot_manager.assign_strategy"),
        ("bot_change_strategy", "bot_manager.change_strategy"),
    ],
)
class TestStrategySwitchExecutors:
    async def test_adopted_calls_manager(
        self, env: _Env, approval_type: str, manager_call: str
    ) -> None:
        params = {"bot_id": "b-1", "strategy_id": "s-adopted"}
        assert await env.executor(approval_type)(params) is None
        assert env.log.calls == [
            ("strategy_registry.get", ("s-adopted",), {}),
            (manager_call, ("b-1", "s-adopted"), {}),
        ]

    @pytest.mark.parametrize(
        ("strategy_id", "message"),
        [
            ("s-x", "전략을 찾을 수 없습니다: s-x"),
            (
                "s-registered",
                "전략이 adopted 상태가 아닙니다: s-registered (registered)",
            ),
            ("s-archived", "전략이 adopted 상태가 아닙니다: s-archived (archived)"),
        ],
    )
    async def test_not_adopted_raises_before_manager_call(
        self,
        env: _Env,
        approval_type: str,
        manager_call: str,
        strategy_id: str,
        message: str,
    ) -> None:
        params = {"bot_id": "b-1", "strategy_id": strategy_id}
        with pytest.raises(ValueError) as ei:
            await env.executor(approval_type)(params)
        assert str(ei.value) == message
        assert env.log.calls == [("strategy_registry.get", (strategy_id,), {})]

    async def test_empty_params_raises_key_error_before_any_call(
        self, env: _Env, approval_type: str, manager_call: str
    ) -> None:
        with pytest.raises(KeyError) as ei:
            await env.executor(approval_type)({})
        assert ei.value.args == ("bot_id",)
        assert env.log.calls == []


class TestAccountExecutors:
    async def test_budget_change(self, env: _Env) -> None:
        await env.executor("budget_change")(
            {"bot_id": "b-1", "amount": 500.0, "account_id": "acc-a"}
        )
        assert env.log.calls == [
            ("treasury_manager.get", ("acc-a",), {}),
            ("treasury.update_budget", ("b-1", 500.0), {}),
        ]

    async def test_rule_change(self, env: _Env) -> None:
        await env.executor("rule_change")(
            {"bot_id": "b-1", "rules": [{"type": "x"}], "account_id": "acc-a"}
        )
        assert env.log.calls == [
            ("rule_engine_manager.get", ("acc-a",), {}),
            ("rule_engine.update_rules", ("b-1", [{"type": "x"}]), {}),
        ]

    @pytest.mark.parametrize("approval_type", ["budget_change", "rule_change"])
    async def test_invalid_account_raises_before_any_call(
        self, env: _Env, approval_type: str
    ) -> None:
        with pytest.raises(InvalidAccountIdError) as ei:
            await env.executor(approval_type)(
                {"bot_id": "b-1", "amount": 1.0, "rules": [], "account_id": ""}
            )
        assert str(ei.value) == (
            f"(approval.{approval_type}.exec) 유효한 account_id가 필요합니다: ''. "
            "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다."
        )
        assert env.log.calls == []


class TestStrategyValidators:
    @pytest.mark.parametrize(
        ("params", "expected", "calls"),
        [
            ({}, [("fail", "strategy_id가 누락되었습니다", "system")], []),
            (
                {"strategy_id": "s-adopted"},
                [("fail", "report_id가 누락되었습니다", "system")],
                [],
            ),
            (
                {"strategy_id": "s-x", "report_id": "r-1"},
                [("fail", "전략을 찾을 수 없습니다", "system")],
                [("strategy_registry.get", ("s-x",), {})],
            ),
            pytest.param(
                {"strategy_id": "s-adopted", "report_id": "r-does-not-exist"},
                [("fail", "리포트를 찾을 수 없습니다: r-does-not-exist", "system")],
                [
                    ("strategy_registry.get", ("s-adopted",), {}),
                    ("report_store.get", ("r-does-not-exist",), {}),
                ],
                id="unknown_report_fails-issue_2686",
            ),
            (
                {"strategy_id": "s-adopted", "report_id": "r-1"},
                [("pass", "", "system")],
                [
                    ("strategy_registry.get", ("s-adopted",), {}),
                    ("report_store.get", ("r-1",), {}),
                ],
            ),
        ],
    )
    async def test_adopt(
        self, env: _Env, params: dict[str, Any], expected: Any, calls: Any
    ) -> None:
        assert await _validate(env, "strategy_adopt", params) == expected
        assert env.log.calls == calls

    @pytest.mark.parametrize(
        ("params", "expected", "calls"),
        [
            ({}, [("fail", "strategy_id가 누락되었습니다", "system")], []),
            (
                {"strategy_id": "s-x", "report_id": "r-1"},
                [("fail", "전략을 찾을 수 없습니다", "system")],
                [("strategy_registry.get", ("s-x",), {})],
            ),
            (
                {"strategy_id": "s-archived", "report_id": "r-1"},
                [("fail", "이미 보관된 전략입니다", "system")],
                [("strategy_registry.get", ("s-archived",), {})],
            ),
            pytest.param(
                {"strategy_id": "s-adopted"},
                [("fail", "report_id가 누락되었습니다", "system")],
                [],
                id="no_report_id_fails-issue_2686",
            ),
            pytest.param(
                {"strategy_id": "s-adopted", "report_id": "r-does-not-exist"},
                [("pass", "", "system")],
                [("strategy_registry.get", ("s-adopted",), {})],
                id="unknown_report_not_looked_up-issue_2900",
            ),
        ],
    )
    async def test_retire(
        self, env: _Env, params: dict[str, Any], expected: Any, calls: Any
    ) -> None:
        assert await _validate(env, "strategy_retire", params) == expected
        assert env.log.calls == calls


def _create_params(bot_id: str, strategy_id: str) -> dict[str, Any]:
    return {
        "config": {"bot_id": bot_id, "strategy_id": strategy_id, "account_id": "acc-a"}
    }


class TestBotValidators:
    @pytest.mark.parametrize(
        ("params", "expected", "calls"),
        [
            (
                {},
                [
                    (
                        "fail",
                        "bot_create params.config가 누락되었습니다",
                        "system:bot_manager",
                    )
                ],
                [],
            ),
            (
                _create_params("b-new", "s-adopted"),
                [("pass", "", "system:bot_manager")],
                [
                    ("bot_manager.get_bot", ("b-new",), {}),
                    ("strategy_registry.get", ("s-adopted",), {}),
                ],
            ),
            (
                _create_params("b-stopped", "s-x"),
                [
                    (
                        "fail",
                        "동일 ID의 봇이 이미 존재: b-stopped",
                        "system:bot_manager",
                    ),
                    (
                        "fail",
                        "전략을 찾을 수 없습니다: s-x",
                        "system:strategy_registry",
                    ),
                ],
                [
                    ("bot_manager.get_bot", ("b-stopped",), {}),
                    ("strategy_registry.get", ("s-x",), {}),
                ],
            ),
            (
                _create_params("", "s-registered"),
                [
                    (
                        "fail",
                        "전략이 adopted 상태가 아닙니다: s-registered",
                        "system:strategy_registry",
                    )
                ],
                [("strategy_registry.get", ("s-registered",), {})],
            ),
        ],
    )
    async def test_create(
        self, env: _Env, params: dict[str, Any], expected: Any, calls: Any
    ) -> None:
        assert await _validate(env, "bot_create", params) == expected
        assert env.log.calls == calls

    async def test_delete_missing_bot(self, env: _Env) -> None:
        assert await _validate(env, "bot_delete", {"bot_id": "b-x"}) == [
            ("fail", "봇이 존재하지 않음", "system:bot_manager")
        ]
        assert env.log.calls == [("bot_manager.get_bot", ("b-x",), {})]

    async def test_delete_stopped_no_positions_passes(self, env: _Env) -> None:
        assert await _validate(env, "bot_delete", {"bot_id": "b-stopped"}) == [
            ("pass", "", "system:bot_manager")
        ]
        assert env.log.calls == [
            ("bot_manager.get_bot", ("b-stopped",), {}),
            (
                "position_history.get_positions_sync",
                ("b-stopped",),
                {"account_id": "acc-a"},
            ),
        ]

    async def test_delete_running_with_one_position_fails_twice(
        self, env: _Env
    ) -> None:
        env.s.position_history.positions["b-running"] = [object()]
        assert await _validate(env, "bot_delete", {"bot_id": "b-running"}) == [
            ("fail", "봇이 running 상태 (stopped 필요)", "system:bot_manager"),
            ("fail", "보유 포지션 1건 존재", "system:trade"),
        ]
        assert env.log.calls == [
            ("bot_manager.get_bot", ("b-running",), {}),
            (
                "position_history.get_positions_sync",
                ("b-running",),
                {"account_id": "acc-a"},
            ),
        ]

    async def test_change_strategy_missing_bot(self, env: _Env) -> None:
        params = {"bot_id": "b-x", "strategy_id": "s-x"}
        assert await _validate(env, "bot_change_strategy", params) == [
            ("fail", "봇이 존재하지 않음", "system:bot_manager")
        ]
        assert env.log.calls == [("bot_manager.get_bot", ("b-x",), {})]

    @pytest.mark.parametrize(
        ("bot_id", "strategy_id", "expected"),
        [
            ("b-stopped", "s-adopted", [("pass", "", "system:bot_manager")]),
            (
                "b-error",
                "s-adopted",
                [("fail", "봇이 error 상태 (stopped 필요)", "system:bot_manager")],
            ),
            (
                "b-running",
                "s-adopted",
                [("fail", "봇이 running 상태 (stopped 필요)", "system:bot_manager")],
            ),
            (
                "b-stopped",
                "s-x",
                [("fail", "전략을 찾을 수 없습니다: s-x", "system:strategy_registry")],
            ),
            (
                "b-stopped",
                "s-archived",
                [
                    (
                        "fail",
                        "전략이 adopted 상태가 아닙니다: s-archived",
                        "system:strategy_registry",
                    )
                ],
            ),
            (
                "b-running",
                "s-registered",
                [
                    ("fail", "봇이 running 상태 (stopped 필요)", "system:bot_manager"),
                    (
                        "fail",
                        "전략이 adopted 상태가 아닙니다: s-registered",
                        "system:strategy_registry",
                    ),
                ],
            ),
            (
                "b-stopped",
                None,
                [("fail", "전략을 찾을 수 없습니다: ", "system:strategy_registry")],
            ),
        ],
    )
    async def test_change_strategy(
        self, env: _Env, bot_id: str, strategy_id: str | None, expected: Any
    ) -> None:
        params: dict[str, Any] = {"bot_id": bot_id}
        if strategy_id is not None:
            params["strategy_id"] = strategy_id
        assert await _validate(env, "bot_change_strategy", params) == expected
        assert env.log.calls == [
            ("bot_manager.get_bot", (bot_id,), {}),
            ("strategy_registry.get", (strategy_id or "",), {}),
        ]

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            (
                {},
                ("fail", "전략을 찾을 수 없습니다: ", "system:strategy_registry"),
            ),
            (
                {"bot_id": "b-x", "strategy_id": "s-x"},
                ("fail", "전략을 찾을 수 없습니다: s-x", "system:strategy_registry"),
            ),
            (
                {"bot_id": "b-running", "strategy_id": "s-registered"},
                (
                    "fail",
                    "전략이 adopted 상태가 아닙니다: s-registered",
                    "system:strategy_registry",
                ),
            ),
            (
                {"bot_id": "b-running", "strategy_id": "s-archived"},
                (
                    "fail",
                    "전략이 adopted 상태가 아닙니다: s-archived",
                    "system:strategy_registry",
                ),
            ),
            (
                {"bot_id": "b-running", "strategy_id": "s-adopted"},
                ("pass", "", "system:strategy_registry"),
            ),
        ],
    )
    async def test_assign_strategy_requires_adopted_strategy(
        self, env: _Env, params: dict[str, Any], expected: Any
    ) -> None:
        assert await _validate(env, "bot_assign_strategy", params) == [expected]
        assert env.log.calls == [
            ("strategy_registry.get", (params.get("strategy_id", ""),), {})
        ]

    @pytest.mark.parametrize(
        ("bot_id", "expected"),
        [
            ("b-x", [("fail", "봇이 존재하지 않음", "system:bot_manager")]),
            ("b-stopped", [("pass", "", "system:bot_manager")]),
            ("b-error", [("pass", "", "system:bot_manager")]),
            (
                "b-running",
                [
                    (
                        "fail",
                        "봇이 running 상태 (stopped/error 필요)",
                        "system:bot_manager",
                    )
                ],
            ),
        ],
    )
    async def test_resume(self, env: _Env, bot_id: str, expected: Any) -> None:
        assert await _validate(env, "bot_resume", {"bot_id": bot_id}) == expected
        assert env.log.calls == [("bot_manager.get_bot", (bot_id,), {})]


class TestBudgetValidator:
    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            (
                {"amount": 1000.0, "current": 0, "account_id": "acc-a"},
                [("pass", "", "system:treasury")],
            ),
            (
                {"amount": 1001.0, "current": 0, "account_id": "acc-a"},
                [
                    (
                        "warn",
                        "미할당 잔액(1,000원) < 증액분(1,001원)",
                        "system:treasury",
                    )
                ],
            ),
            (
                {"amount": 100.0, "current": 5000.0, "account_id": "acc-a"},
                [("pass", "", "system:treasury")],
            ),
            (
                {"account_id": "acc-a"},
                [("pass", "", "system:treasury")],
            ),
        ],
    )
    async def test_amount_paths(
        self, env: _Env, params: dict[str, Any], expected: Any
    ) -> None:
        assert await _validate(env, "budget_change", params) == expected
        assert env.log.calls == [("treasury_manager.get", ("acc-a",), {})]

    async def test_missing_treasury_fails(self, env: _Env) -> None:
        assert await _validate(env, "budget_change", {"account_id": "acc-z"}) == [
            ("fail", "계좌 'acc-z'의 Treasury 없음", "system:treasury")
        ]
        assert env.log.calls == [("treasury_manager.get", ("acc-z",), {})]

    async def test_invalid_account_fails_before_any_call(self, env: _Env) -> None:
        assert await _validate(env, "budget_change", {"amount": 1.0}) == [
            (
                "fail",
                "(approval.budget_change.validate) "
                "유효한 account_id가 필요합니다: None. "
                "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다.",
                "system:treasury",
            )
        ]
        assert env.log.calls == []


class TestLateBinding:
    async def test_replaced_bot_manager_is_used(self, env: _Env) -> None:
        env.s.bot_manager = _BotManager(
            env.log, {"b-1": _bot("b-1", BotStatus.STOPPED)}, tag="new_bot_manager"
        )
        await env.executor("bot_resume")({"bot_id": "b-1"})
        params = {"bot_id": "b-1", "strategy_id": "s-adopted"}
        assert await _validate(env, "bot_change_strategy", params) == [
            ("pass", "", "system:bot_manager")
        ]
        assert env.log.calls == [
            ("new_bot_manager.resume_bot", ("b-1",), {}),
            ("new_bot_manager.get_bot", ("b-1",), {}),
            ("strategy_registry.get", ("s-adopted",), {}),
        ]

    async def test_replaced_treasury_manager_is_used(self, env: _Env) -> None:
        env.s.treasury_manager = _TreasuryManager(
            env.log, {"acc-a": _Treasury(env.log, unallocated=5.0)}
        )
        assert await _validate(
            env, "budget_change", {"amount": 6.0, "account_id": "acc-a"}
        ) == [("warn", "미할당 잔액(5원) < 증액분(6원)", "system:treasury")]


def test_importing_approval_package_does_not_load_handlers_or_domains() -> None:
    code = (
        "import sys\n"
        "import ante.approval\n"
        "names = (\n"
        "    'ante.approval.handlers', 'ante.bot', 'ante.report', 'ante.strategy'\n"
        ")\n"
        "print(sorted(n for n in names if n in sys.modules))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "ANTE_CONFIG_DIR"}
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "[]\n"
