"""CommandRegistry 테스트."""

import typing

import pytest

from ante.contracts.vocab import ContractKind
from ante.ipc.registry import (
    AccountIdPolicy,
    CommandRegistry,
    CommandSpec,
    ShutdownBehavior,
    register_all_handlers,
)


@pytest.fixture
def registry() -> CommandRegistry:
    return CommandRegistry()


def test_register_and_get(registry: CommandRegistry) -> None:
    """핸들러 등록 후 조회.

    Refs #1849: ``register()`` 3-인자 호출은 신규 7 필드의 default 값(``raw``
    / ``None`` / 빈 frozenset / ``None`` / ``"none"`` / 빈 tuple / ``None``)
    으로 채워진 ``CommandSpec``과 일치해야 한다(backward compat lock).
    """

    async def dummy_handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {"ok": True}

    registry.register("test.command", dummy_handler, is_mutating=True)
    spec = registry.get("test.command")
    assert spec == CommandSpec(
        name="test.command",
        handler=dummy_handler,
        is_mutating=True,
    )
    # 신규 필드 default 값 명시 검증 (frozen dataclass eq에 포함).
    assert spec is not None
    assert spec.result_kind == "raw"
    assert spec.result_key is None
    assert spec.required_services == frozenset()
    assert spec.audit_action is None
    assert spec.account_id_policy == "none"
    assert spec.cross_validators == ()
    assert spec.shutdown_behavior is None


def test_get_unregistered_returns_none(registry: CommandRegistry) -> None:
    """미등록 커맨드 조회 시 None 반환."""
    assert registry.get("nonexistent.command") is None


def test_commands_property(registry: CommandRegistry) -> None:
    """commands 프로퍼티가 등록된 커맨드 목록을 반환."""

    async def handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {}

    registry.register("a.command", handler, is_mutating=True)
    registry.register("b.command", handler, is_mutating=False)
    assert set(registry.commands) == {"a.command", "b.command"}


def test_register_all_handlers() -> None:
    """register_all_handlers가 28개 핸들러를 등록 (account.delete 제외).

    `account.delete`는 1.0 IPC 계약에서 제거되어 cold-path CLI에서 직접
    AccountService를 호출한다.

    Refs #1418 → #1472 SPLIT-D: ``approval.cancel_invalid`` 추가 (16번째
    mutating).

    Refs #1712: ``bot.start`` / ``bot.stop`` (mutating, 17~18) /
    ``bot.status`` (read-only, 4번째) 추가.

    Browser/HTTP 제거 parity: retained 운영 mutation 5개를 CLI/IPC로
    이전하면서 ``bot.update``, ``treasury.set_balance``, ``rule.update``,
    ``strategy.set_status``, ``member.update_scopes``를 추가.

    Refs #2111: ``bot.signal_key.rotate`` (mutating) 추가 — ``bot signal-key
    --rotate`` 의 runtime IPC 경로.
    """
    registry = CommandRegistry()
    register_all_handlers(registry)
    assert len(registry.commands) == 28

    expected = {
        "system.halt",
        "system.clear_halt",
        "account.suspend",
        "account.activate",
        "bot.create",
        "bot.remove",
        "bot.signal_key.rotate",
        "bot.start",
        "bot.stop",
        "bot.update",
        "bot.status",
        "treasury.allocate",
        "treasury.deallocate",
        "treasury.set_balance",
        "rule.update",
        "strategy.set_status",
        "member.update_scopes",
        "config.set",
        "approval.request",
        "approval.approve",
        "approval.reject",
        "approval.cancel",
        "approval.cancel_invalid",
        "approval.reopen",
        "broker.status",
        "broker.balance",
        "broker.positions",
        "broker.reconcile",
    }
    assert set(registry.commands) == expected
    # account.delete는 cold-path 전용이므로 IPC 등록 대상이 아니다.
    assert "account.delete" not in registry.commands
    # legacy system.activate는 system.clear_halt로 교체됨 (Refs #1213, #1212 SSOT)
    assert "system.activate" not in registry.commands


def test_register_all_handlers_taxonomy() -> None:
    """등록된 28개 핸들러의 mutating/read-only taxonomy가 스펙과 일치한다.

    Refs #1712: ``bot.start`` / ``bot.stop`` mutating, ``bot.status``
    read-only — ``docs/specs/ipc/ipc.md`` Handler taxonomy SSOT 와 동기화.

    Refs #2111: ``bot.signal_key.rotate`` mutating 추가.
    """
    registry = CommandRegistry()
    register_all_handlers(registry)

    mutating = {
        "system.halt",
        "system.clear_halt",
        "account.suspend",
        "account.activate",
        "bot.create",
        "bot.remove",
        "bot.signal_key.rotate",
        "bot.start",
        "bot.stop",
        "bot.update",
        "treasury.allocate",
        "treasury.deallocate",
        "treasury.set_balance",
        "rule.update",
        "strategy.set_status",
        "member.update_scopes",
        "config.set",
        "approval.request",
        "approval.approve",
        "approval.reject",
        "approval.cancel",
        "approval.cancel_invalid",
        "approval.reopen",
        "broker.reconcile",
    }
    read_only = {
        "broker.status",
        "broker.balance",
        "broker.positions",
        "bot.status",
    }

    assert len(mutating) == 24
    assert len(read_only) == 4
    assert mutating | read_only == set(registry.commands)

    for command in mutating:
        spec = registry.get(command)
        assert spec is not None
        assert spec.is_mutating is True

    for command in read_only:
        spec = registry.get(command)
        assert spec is not None
        assert spec.is_mutating is False


# ── _handle_bot_create 변환 로직 테스트 ──────────────


class TestHandleBotCreate:
    async def test_creates_bot_with_config_and_strategy(self):
        """strategy_id → StrategyLoader → BotConfig → create_bot 변환."""
        from dataclasses import dataclass
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_bot_create

        @dataclass
        class FakeRecord:
            filepath: str = "/tmp/strategy.py"

        fake_registry = AsyncMock()
        fake_registry.get.return_value = FakeRecord()

        fake_bot = MagicMock()
        fake_bot.bot_id = "new-bot"

        fake_bot_manager = AsyncMock()
        fake_bot_manager.create_bot.return_value = fake_bot

        svc = MagicMock()
        svc.strategy_registry = fake_registry
        svc.bot_manager = fake_bot_manager

        # StrategyLoader.load를 모킹
        import ante.strategy.loader

        original_load = ante.strategy.loader.StrategyLoader.load
        ante.strategy.loader.StrategyLoader.load = MagicMock(
            return_value=type("FakeStrategy", (), {})
        )
        try:
            result = await _handle_bot_create(
                svc,
                {
                    "strategy_id": "strat-1",
                    "name": "테스트봇",
                    "account_id": "acct-1",
                    "interval_seconds": 30,
                },
                "cli-user",
            )
        finally:
            ante.strategy.loader.StrategyLoader.load = original_load

        assert result == {"bot_id": "new-bot"}
        fake_registry.get.assert_awaited_once_with("strat-1")
        fake_bot_manager.create_bot.assert_awaited_once()
        call_kwargs = fake_bot_manager.create_bot.call_args.kwargs
        assert call_kwargs["config"].strategy_id == "strat-1"
        assert call_kwargs["config"].name == "테스트봇"
        assert call_kwargs["config"].account_id == "acct-1"
        assert call_kwargs["config"].interval_seconds == 30

    async def test_raises_when_strategy_not_found(self):
        """미등록 strategy_id → ValueError.

        #1656 E bucket: ``_handle_bot_create`` 가 ``require_account_id`` 를
        함수 최상단(strategy lookup 이전)으로 옮겼으므로, 순수
        strategy-not-found ``ValueError`` 경로를 검증하려면 **valid**
        account_id 를 payload에 포함해야 한다(account 검증을 통과한 뒤
        strategy lookup 도달). account_id 누락 시 #1656 validate-first 로
        ``InvalidAccountIdError`` 가 먼저 raise되어 본 테스트 의도(순수
        strategy-not-found)가 가려진다.
        """
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_bot_create

        fake_registry = AsyncMock()
        fake_registry.get.return_value = None

        svc = MagicMock()
        svc.strategy_registry = fake_registry

        with pytest.raises(ValueError, match="전략을 찾을 수 없습니다"):
            await _handle_bot_create(
                svc,
                {"strategy_id": "nonexistent", "account_id": "acct-1"},
                "cli-user",
            )

    async def test_ipc_bot_create_account_scoped_required(self):
        """Refs #1217 → #1241 SPLIT-2 / #1656: invalid/missing ``account_id`` 시
        ``InvalidAccountIdError`` 로 거부한다.

        ``args.get("account_id")`` fallback 이 제거되어 IPC routing 진입점에서
        즉시 거부된다. #1656 E bucket: ``require_account_id`` 가 함수 최상단
        (strategy_registry.get / StrategyLoader.load 이전)으로 이동했으므로
        strategy mock / StrategyLoader monkeypatch workaround 없이도(실제
        strategy 처리 이전) ``ipc.bot.create`` context 로 먼저 실패한다.
        """
        from unittest.mock import AsyncMock, MagicMock

        from ante.account.errors import InvalidAccountIdError
        from ante.ipc.registry import _handle_bot_create

        fake_bot_manager = AsyncMock()

        svc = MagicMock()
        svc.bot_manager = fake_bot_manager

        # 누락 → 거부 (validate-first: strategy mock 불필요)
        with pytest.raises(InvalidAccountIdError, match="ipc.bot.create"):
            await _handle_bot_create(
                svc,
                {"strategy_id": "strat-1"},
                "cli-user",
            )

        # 빈 문자열 → 거부
        with pytest.raises(InvalidAccountIdError):
            await _handle_bot_create(
                svc,
                {"strategy_id": "strat-1", "account_id": ""},
                "cli-user",
            )

        # 'default' 예약어 → 거부
        with pytest.raises(InvalidAccountIdError):
            await _handle_bot_create(
                svc,
                {"strategy_id": "strat-1", "account_id": "default"},
                "cli-user",
            )

        # 패턴 위반 → 거부
        with pytest.raises(InvalidAccountIdError):
            await _handle_bot_create(
                svc,
                {"strategy_id": "strat-1", "account_id": "bad_id!"},
                "cli-user",
            )

        # bot_manager.create_bot 까지 절대 도달하지 않아야 한다
        fake_bot_manager.create_bot.assert_not_called()

    async def test_bot_create_validate_first_skips_strategy_lookup_and_load(self):
        """#1656 E bucket validate-first 회귀: invalid/missing ``account_id`` 면
        ``strategy_registry.get`` 과 ``StrategyLoader.load`` 가 **호출되지
        않는다**(account 검증이 strategy 처리보다 먼저).

        ``_handle_bot_create`` 가 ``require_account_id`` 를 함수 최상단으로
        옮긴 계약(strategy lookup/load 이전)을 spy 로 고정한다. 이전 순서
        (strategy lookup → load → 늦은 require_account_id)에서는 invalid
        account_id 라도 strategy_registry.get / StrategyLoader.load 가 먼저
        호출되어 본 단언이 실패한다(failing check before fix).
        """
        from unittest.mock import AsyncMock, MagicMock

        from ante.account.errors import InvalidAccountIdError
        from ante.ipc.registry import _handle_bot_create

        fake_registry = AsyncMock()

        svc = MagicMock()
        svc.strategy_registry = fake_registry

        import ante.strategy.loader

        load_calls: list = []
        original_load = ante.strategy.loader.StrategyLoader.load
        ante.strategy.loader.StrategyLoader.load = (  # type: ignore[assignment]
            lambda path: load_calls.append(path)
        )
        try:
            for bad_args in (
                {"strategy_id": "strat-1"},  # account_id 키 생략
                {"strategy_id": "strat-1", "account_id": ""},
                {"strategy_id": "strat-1", "account_id": "default"},
                {"strategy_id": "strat-1", "account_id": "bad_id!"},
            ):
                with pytest.raises(InvalidAccountIdError):
                    await _handle_bot_create(svc, bad_args, "cli-user")

            # validate-first: account 검증이 먼저 raise되어 strategy lookup /
            # load 가 절대 호출되지 않는다.
            fake_registry.get.assert_not_called()
            assert load_calls == [], load_calls
        finally:
            ante.strategy.loader.StrategyLoader.load = original_load


# ── system.halt / system.clear_halt 응답 shape (Refs #1213) ──


class TestSystemKillSwitchHandlers:
    """system.halt / system.clear_halt IPC 응답 shape 회귀 가드.

    IPC는 status, accounts_changed, changed_at, accounts[] shape를 사용한다.
    """

    @pytest.mark.asyncio
    async def test_handle_system_halt_response_shape(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_system_halt

        accounts = [
            {
                "account_id": "acc1",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            },
            {
                "account_id": "acc2",
                "previous_status": "suspended",
                "status": "suspended",
                "changed": False,
            },
        ]

        svc = MagicMock()
        svc.account = MagicMock()
        svc.account.suspend_all = AsyncMock(return_value=accounts)

        result = await _handle_system_halt(svc, {"reason": "test"}, "cli-user")

        assert result["status"] == "halted"
        assert result["accounts_changed"] == 1
        assert result["accounts"] == accounts
        assert isinstance(result["changed_at"], str) and result["changed_at"]
        svc.account.suspend_all.assert_awaited_once_with(
            reason="test", suspended_by="cli-user"
        )

    @pytest.mark.asyncio
    async def test_handle_system_clear_halt_response_shape(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_system_clear_halt

        accounts = [
            {
                "account_id": "acc1",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            },
        ]

        svc = MagicMock()
        svc.account = MagicMock()
        svc.account.activate_all = AsyncMock(return_value=accounts)

        # bot_manager.start*/restart* 같은 메서드가 호출되지 않음을 보장하려면
        # bot_manager 자체가 호출되지 않아야 한다 (clear_halt 핸들러는 BotManager
        # 의존성을 직접 보유하지 않는다 — Refs #1213 회귀 가드).
        svc.bot_manager = MagicMock()

        result = await _handle_system_clear_halt(svc, {}, "cli-user")

        assert result["status"] == "halt_cleared"
        assert result["accounts_changed"] == 1
        assert result["accounts"] == accounts
        assert isinstance(result["changed_at"], str) and result["changed_at"]
        svc.account.activate_all.assert_awaited_once_with(activated_by="cli-user")
        # 봇 자동 재시작 회귀 가드: BotManager 메서드가 호출되지 않아야 한다.
        svc.bot_manager.start_bot.assert_not_called()
        svc.bot_manager.restart_bot.assert_not_called()
        svc.bot_manager.start_all.assert_not_called()


# ── broker.reconcile account-level 재설계 (#2119/2121/2122/2118/2120) ──


def _make_reconcile_svc(
    *,
    bots: list[dict],
    broker_positions: list[dict] | None = None,
):
    """account-level reconcile 핸들러용 svc mock 을 만든다.

    - ``svc.account.get_broker(account_id)`` → broker mock(``get_account_positions``)
    - ``svc.bot_manager.list_bots()`` → ``bots``
    - ``svc.reconciler`` → reconcile/detect_account_level/compute_account_diff mock
    """
    from unittest.mock import AsyncMock, MagicMock

    broker = AsyncMock()
    broker.get_account_positions = AsyncMock(
        return_value=broker_positions if broker_positions is not None else []
    )

    account_svc = AsyncMock()
    account_svc.get_broker = AsyncMock(return_value=broker)

    bot_manager = MagicMock()
    bot_manager.list_bots = MagicMock(return_value=bots)

    reconciler = AsyncMock()
    reconciler.reconcile = AsyncMock(return_value=[])
    reconciler.detect_account_level = AsyncMock(return_value=[])
    reconciler.compute_account_diff = AsyncMock(return_value=[])

    svc = MagicMock()
    svc.account = account_svc
    svc.bot_manager = bot_manager
    svc.reconciler = reconciler
    return svc, broker, reconciler


class TestHandleBrokerReconcileAccountLevel:
    """``broker.reconcile`` IPC 핸들러 account-level 재설계 (#2119).

    bot_id 없이 account_id 만으로 도달하고, 서버 BrokerAdapter 가 계좌 총합을
    직접 조회하며(#2121), fix 플래그를 준수하고(#2122), 봇 count 로 보정/탐지를
    분기한다(1봇=위임 / 2+봇·0봇=detect-only).
    """

    @pytest.mark.asyncio
    async def test_reaches_account_level_without_bot_id(self):
        """(a) bot_id 없이 account_id 만으로 도달하고 서버 broker 를 조회한다."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[{"bot_id": "bot-1", "status": "running", "account_id": "acc-a"}],
            broker_positions=[{"symbol": "005930", "quantity": 10, "avg_price": 1}],
        )

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": True}, "cli-user"
        )

        # 서버 broker 조회 (caller-supplied 무시).
        svc.account.get_broker.assert_awaited_once_with("acc-a")
        broker.get_account_positions.assert_awaited_once()
        assert result["account_id"] == "acc-a"
        assert result["bot_count"] == 1

    @pytest.mark.asyncio
    async def test_fix_false_dry_run_no_correction(self):
        """(b) fix=False → 단일봇 reconcile(dry_run=True) — correct_position 미호출."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[{"bot_id": "bot-1", "status": "running", "account_id": "acc-a"}],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": False}, "cli-user"
        )

        reconciler.reconcile.assert_awaited_once()
        assert reconciler.reconcile.call_args.kwargs["dry_run"] is True
        assert result["fix"] is False
        assert result["fix_applied"] is False

    @pytest.mark.asyncio
    async def test_single_bot_fix_true_delegates_correction(self):
        """(c) 1봇 계좌 fix=True → 기존 reconcile 보정(dry_run=False) 위임."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[{"bot_id": "bot-1", "status": "stopped", "account_id": "acc-a"}],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )
        reconciler.reconcile.return_value = [{"symbol": "005930", "corrected": True}]

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": True}, "cli-user"
        )

        reconciler.reconcile.assert_awaited_once()
        call = reconciler.reconcile.call_args
        assert call.args[0] == "bot-1"
        assert call.kwargs["account_id"] == "acc-a"
        assert call.kwargs["dry_run"] is False
        reconciler.detect_account_level.assert_not_called()
        assert result["corrections"] == 1
        assert result["fix_applied"] is True

    @pytest.mark.asyncio
    async def test_multi_bot_detect_only(self):
        """(d) 2+봇 → detect_account_level (correct_position 미호출)."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[
                {"bot_id": "bot-1", "status": "running", "account_id": "acc-a"},
                {"bot_id": "bot-2", "status": "running", "account_id": "acc-a"},
            ],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )
        reconciler.detect_account_level.return_value = [
            {"symbol": "005930", "broker_qty": 10, "internal_qty": 8, "diff": 2}
        ]

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": True}, "cli-user"
        )

        reconciler.reconcile.assert_not_called()
        reconciler.detect_account_level.assert_awaited_once()
        assert result["bot_count"] == 2
        assert result["adjustments"] == []
        assert result["mismatches"][0]["symbol"] == "005930"
        # detect-only — fix=True 여도 보정은 없다.
        assert result["corrections"] == 0

    @pytest.mark.asyncio
    async def test_ignores_caller_supplied_broker_positions(self):
        """(f) caller-supplied broker_positions 무시 — 서버 broker 조회값 사용."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[{"bot_id": "bot-1", "status": "running", "account_id": "acc-a"}],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )

        await _handle_broker_reconcile(
            svc,
            {
                "account_id": "acc-a",
                "fix": True,
                # 악의/오류 입력 — 무시되어야 한다.
                "broker_positions": [{"symbol": "FAKE", "quantity": 9999}],
            },
            "cli-user",
        )

        # reconcile 에 전달된 broker_positions 는 서버 조회값이어야 한다.
        passed = reconciler.reconcile.call_args.args[1]
        assert passed == [{"symbol": "005930", "quantity": 10}]
        assert all(p["symbol"] != "FAKE" for p in passed)

    @pytest.mark.asyncio
    async def test_zero_bots_with_broker_positions_detect_alert(self):
        """(k) 0봇 + broker_positions 존재 → detect/alert (no-op 아님)."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )
        reconciler.detect_account_level.return_value = [
            {"symbol": "005930", "broker_qty": 10, "internal_qty": 0, "diff": 10}
        ]

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": False}, "cli-user"
        )

        reconciler.reconcile.assert_not_called()
        reconciler.detect_account_level.assert_awaited_once()
        assert result["bot_count"] == 0
        assert result["mismatches"][0]["diff"] == 10

    @pytest.mark.asyncio
    async def test_bot_count_status_agnostic(self):
        """(l) 봇 count 는 status 무관 — stopped/error 봇도 count 에 포함된다."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[
                {"bot_id": "bot-1", "status": "running", "account_id": "acc-a"},
                {"bot_id": "bot-2", "status": "stopped", "account_id": "acc-a"},
                {"bot_id": "bot-3", "status": "error", "account_id": "acc-a"},
            ],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": True}, "cli-user"
        )

        # 3봇(status 무관) → 2+봇 → detect-only.
        assert result["bot_count"] == 3
        reconciler.reconcile.assert_not_called()
        reconciler.detect_account_level.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_account_bots_excluded_from_count(self):
        """다른 계좌 봇은 count 에서 제외된다 (account-scoped count)."""
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[
                {"bot_id": "bot-1", "status": "running", "account_id": "acc-a"},
                {"bot_id": "bot-x", "status": "running", "account_id": "acc-other"},
            ],
            broker_positions=[{"symbol": "005930", "quantity": 10}],
        )

        result = await _handle_broker_reconcile(
            svc, {"account_id": "acc-a", "fix": True}, "cli-user"
        )

        # acc-a 단일봇만 count → reconcile 위임.
        assert result["bot_count"] == 1
        reconciler.reconcile.assert_awaited_once()
        assert reconciler.reconcile.call_args.args[0] == "bot-1"

    @pytest.mark.asyncio
    async def test_require_account_id_rejected(self):
        """(j) require_account_id 회귀 — invalid account_id 는 즉시 거부."""
        from ante.account.errors import InvalidAccountIdError
        from ante.ipc.registry import _handle_broker_reconcile

        svc, broker, reconciler = _make_reconcile_svc(
            bots=[{"bot_id": "bot-1", "status": "running", "account_id": "acc-a"}],
        )

        with pytest.raises(InvalidAccountIdError):
            await _handle_broker_reconcile(
                svc, {"account_id": "default", "fix": True}, "cli-user"
            )

        # broker 조회/reconcile 까지 도달하지 않아야 한다.
        svc.account.get_broker.assert_not_called()
        reconciler.reconcile.assert_not_called()
        reconciler.detect_account_level.assert_not_called()


# ── #1379 oracle A7: IPC config.set 핸들러도 서비스 경계 ValueError 전파 ──


class TestHandleConfigSetValidation:
    """``_handle_config_set`` 이 ``DynamicConfigService.set`` 의 ValueError 를
    그대로 전파하는지 검증한다(IPC 우회 차단, #1379).
    """

    async def test_invalid_log_level_propagates_value_error(self):
        """invalid system.log_level → ValueError (IPC 단계 차단)."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_config_set

        async def _set(key, value, category, changed_by):  # noqa: ANN001, ANN202
            from ante.config.dynamic import validate_value

            validate_value(key, value)

        fake_dynamic = MagicMock()
        fake_dynamic.set = AsyncMock(side_effect=_set)

        svc = MagicMock()
        svc.dynamic_config = fake_dynamic

        with pytest.raises(ValueError, match="system.log_level"):
            await _handle_config_set(
                svc,
                {
                    "key": "system.log_level",
                    "value": "ORACLE_INVALID_LEVEL",
                    "category": "system",
                },
                "cli-user",
            )

    async def test_valid_log_level_succeeds(self):
        """``DEBUG`` 같은 정상 값은 통과."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_config_set

        fake_dynamic = MagicMock()
        fake_dynamic.set = AsyncMock(return_value=None)

        svc = MagicMock()
        svc.dynamic_config = fake_dynamic

        result = await _handle_config_set(
            svc,
            {
                "key": "system.log_level",
                "value": "DEBUG",
                "category": "system",
            },
            "cli-user",
        )
        assert result == {"key": "system.log_level", "value": "DEBUG"}
        fake_dynamic.set.assert_awaited_once()


# ── #1849 CommandSpec metadata 확장 / 27 commands 완전성 ─────────────


class TestCommandSpecMetadataExtension:
    """Refs #1849 (#1819 부모): CommandSpec contract metadata 7 필드 확장.

    * dispatch wrapper 동작 변경은 본 이슈 범위가 아니다(#1850 / #1851).
    * default 값으로 backward compat을 보장하고, 27 commands는 필수값을 가진다.
    """

    def test_command_spec_has_seven_metadata_fields(self) -> None:
        """``CommandSpec``이 신규 7 필드를 dataclass field로 보유한다."""
        from dataclasses import fields

        names = {f.name for f in fields(CommandSpec)}
        # 기존 3 + 신규 7 = 10 필드.
        assert names == {
            "name",
            "handler",
            "is_mutating",
            "result_kind",
            "result_key",
            "required_services",
            "audit_action",
            "account_id_policy",
            "cross_validators",
            "shutdown_behavior",
        }

    def test_register_kwargs_backward_compat(self, registry: CommandRegistry) -> None:
        """``register(name, handler, is_mutating=...)`` 3-인자 호출만으로
        default가 적용된 ``CommandSpec``이 생성된다(기존 호출자 무변경).
        """

        async def handler(svc, args, actor):  # type: ignore[no-untyped-def]
            return {}

        registry.register("legacy.cmd", handler, is_mutating=False)
        spec = registry.get("legacy.cmd")
        assert spec is not None
        assert spec.result_kind == "raw"
        assert spec.result_key is None
        assert spec.required_services == frozenset()
        assert spec.audit_action is None
        assert spec.account_id_policy == "none"
        assert spec.cross_validators == ()
        assert spec.shutdown_behavior is None

    def test_register_kwargs_full_metadata(self, registry: CommandRegistry) -> None:
        """``register()``가 신규 kwargs를 모두 수용하고 ``CommandSpec``에
        전파한다."""

        async def handler(svc, args, actor):  # type: ignore[no-untyped-def]
            return {"bot": {}}

        def _validator(_args: dict) -> None:
            return None

        registry.register(
            "ext.cmd",
            handler,
            is_mutating=True,
            result_kind="entity",
            result_key="bot",
            required_services=frozenset({"bot_manager", "audit_logger"}),
            audit_action="ext.cmd",
            account_id_policy="required",
            cross_validators=(_validator,),
            shutdown_behavior="block_all",
        )
        spec = registry.get("ext.cmd")
        assert spec is not None
        assert spec.result_kind == "entity"
        assert spec.result_key == "bot"
        assert spec.required_services == frozenset({"bot_manager", "audit_logger"})
        assert spec.audit_action == "ext.cmd"
        assert spec.account_id_policy == "required"
        assert spec.cross_validators == (_validator,)
        assert spec.shutdown_behavior == "block_all"

    def test_command_spec_result_kind_uses_contract_kind_vocab(self) -> None:
        """``CommandSpec.result_kind`` annotation이 ``ContractKind`` (#1822)
        Literal alias를 그대로 사용한다(타입 SSOT lock).

        ``CommandSpec``은 ``CommandHandler``를 통해 ``"ServiceRegistry"``
        forward reference를 포함하므로 ``typing.get_type_hints``는 runtime에
        실패할 수 있다. annotation 문자열과 default 값으로 lock 한다.
        """
        from dataclasses import fields

        result_kind_field = next(
            f for f in fields(CommandSpec) if f.name == "result_kind"
        )
        # annotation은 string 또는 typing alias 형태. ``ContractKind`` SSOT
        # 와 정합한지 string 표현으로 확인.
        annotation = result_kind_field.type
        if isinstance(annotation, str):
            assert annotation == "ContractKind", annotation
        else:
            assert annotation is ContractKind
        # default 값은 ``"raw"``.
        assert result_kind_field.default == "raw"
        # ContractKind 값 집합과 default 정합.
        assert result_kind_field.default in typing.get_args(ContractKind)

    def test_shutdown_behavior_alias_values(self) -> None:
        """``ShutdownBehavior`` Literal alias 값 집합 lock (Codex v2 c1)."""
        assert set(typing.get_args(ShutdownBehavior)) == {
            "block_on_mutating",
            "block_all",
            "allow_all",
        }

    def test_account_id_policy_alias_values(self) -> None:
        """``AccountIdPolicy`` Literal alias 값 집합 lock."""
        assert set(typing.get_args(AccountIdPolicy)) == {
            "none",
            "required",
            "optional_filter",
        }


class TestRegisteredCommandsMetadataCompleteness:
    """Refs #1849: ``register_all_handlers``로 등록되는 27 commands가 필수
    metadata를 모두 가진다."""

    @pytest.fixture
    def loaded(self) -> CommandRegistry:
        reg = CommandRegistry()
        register_all_handlers(reg)
        return reg

    def test_all_commands_result_kind_is_contract_kind(
        self, loaded: CommandRegistry
    ) -> None:
        """27 commands 모두 ``result_kind``가 ``ContractKind`` vocabulary
        (#1822) 값에 포함된다."""
        allowed = set(typing.get_args(ContractKind))
        assert allowed == {"entity", "operation", "collection", "raw", "stream"}
        for spec in loaded.iter_specs():
            assert spec.result_kind in allowed, (
                f"{spec.name} result_kind={spec.result_kind!r} not in ContractKind"
            )

    def test_all_commands_required_services_non_empty(
        self, loaded: CommandRegistry
    ) -> None:
        """27 commands 모두 ``required_services``를 1개 이상 보유한다.

        Ante 서버 IPC handler는 ``ServiceRegistry``에 의존하므로 빈
        ``required_services``는 metadata 누락의 신호.
        """
        for spec in loaded.iter_specs():
            assert spec.required_services, (
                f"{spec.name} has no required_services declared"
            )
            assert isinstance(spec.required_services, frozenset)

    def test_all_commands_required_services_are_strings(
        self, loaded: CommandRegistry
    ) -> None:
        """``required_services`` 항목은 ``ServiceRegistry`` attribute 이름
        문자열이어야 한다."""
        for spec in loaded.iter_specs():
            for name in spec.required_services:
                assert isinstance(name, str) and name, (
                    f"{spec.name} required_services has non-string item {name!r}"
                )

    def test_all_commands_account_id_policy_valid(
        self, loaded: CommandRegistry
    ) -> None:
        """27 commands 모두 ``account_id_policy``가 정의된 Literal 값을
        가진다."""
        allowed = set(typing.get_args(AccountIdPolicy))
        for spec in loaded.iter_specs():
            assert spec.account_id_policy in allowed, (
                f"{spec.name} account_id_policy={spec.account_id_policy!r}"
            )

    def test_audit_action_only_for_audit_logger_dependent_commands(
        self, loaded: CommandRegistry
    ) -> None:
        """``audit_action``이 설정된 명령은 ``required_services``에
        ``audit_logger``를 보유해야 한다(metadata 자기일관성).

        Refs #1819 본문 / Codex v2 condition 3: mutating이라는 사실만으로
        audit_action을 강제하지 않는다. ``audit_action``이 ``None``이면
        ``audit_logger``가 ``required_services``에 없어도 무방.
        """
        for spec in loaded.iter_specs():
            if spec.audit_action is not None:
                assert "audit_logger" in spec.required_services, (
                    f"{spec.name} declares audit_action="
                    f"{spec.audit_action!r} but audit_logger not in "
                    f"required_services={sorted(spec.required_services)!r}"
                )

    def test_audit_actions_match_known_set(self, loaded: CommandRegistry) -> None:
        """``audit_action`` 값들이 실제 handler ``audit_logger.log(action=...)``
        호출과 정합한다(#1849 plan B step).

        본 단언은 registry 내 audit_logger 호출 grep 결과와 1:1로 lock 한다.
        호출 추가/삭제 시 양쪽을 동기화하지 않으면 본 테스트가 회귀를 잡는다.

        Refs #1852 (#1819 epic): account.suspend / account.activate 가 wrapper
        migration 으로 audit_action 부여(7→9 commands).

        Refs #1853 (#1819 epic 종결): rule.update 의 audit 호출을 wrapper 로
        이전(action="account.rule.update", helper 의 기존 action 이름 보존)
        (9→10 commands).

        Refs #2111: ``bot.signal_key.rotate`` 가 audit_action 부여
        (action="bot.signal_key.rotate", audit.md:121 SSOT) (10→11 commands).
        """
        expected_actions = {
            "account.suspend",
            "account.activate",
            "bot.start",
            "bot.stop",
            "bot.update",
            "bot.signal_key.rotate",
            "treasury.set_balance",
            "strategy.set_status",
            "member.update_scopes",
            "approval.cancel_invalid",
            "account.rule.update",
        }
        actual = {
            spec.audit_action
            for spec in loaded.iter_specs()
            if spec.audit_action is not None
        }
        assert actual == expected_actions

    def test_shutdown_behavior_default_none_preserves_legacy_dispatch(
        self, loaded: CommandRegistry
    ) -> None:
        """27 commands 모두 ``shutdown_behavior``를 ``None``으로 두어 기존
        ``IPCServer._dispatch`` ``is_mutating`` 기반 분기(#1184)를 보존한다.

        override 도입은 후속 이슈 책임이며, 본 이슈는 기본 derive 동작만
        유지한다(shutdown 회귀 lock).
        """
        for spec in loaded.iter_specs():
            assert spec.shutdown_behavior is None, (
                f"{spec.name} shutdown_behavior={spec.shutdown_behavior!r} "
                "override는 본 이슈 범위가 아님"
            )

    def test_cross_validators_default_empty(self, loaded: CommandRegistry) -> None:
        """27 commands 모두 ``cross_validators``가 빈 tuple(default).

        skeleton 도입만 본 이슈 범위. 실제 validator wiring은 후속 이슈에서.
        """
        for spec in loaded.iter_specs():
            assert spec.cross_validators == (), spec.name

    def test_iter_specs_returns_all_28_specs(self, loaded: CommandRegistry) -> None:
        """``iter_specs``가 28 commands 모두를 ``CommandSpec`` 인스턴스로
        반환한다."""
        specs = loaded.iter_specs()
        assert len(specs) == 28
        assert all(isinstance(s, CommandSpec) for s in specs)
        # 등록 순서 보존(dict insertion order).
        assert [s.name for s in specs] == loaded.commands
