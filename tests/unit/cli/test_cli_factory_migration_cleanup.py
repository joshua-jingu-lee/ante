"""account/member/approval factory migration cleanup 회귀 lock (#1856).

#1855 ``open_cli_db`` 기반 factory composition 으로 전환된 후, 다음 invariant 들이
유지됨을 검증한다.

Plan v2 SSOT — 10 시나리오:

1. ``_create_account_service`` factory 가 normal exit 에서 ``Database.close`` 를
   호출한다.
2. ``_create_account_service`` factory 가 ``AccountService.initialize`` 실패 시
   ``Database.close`` 를 호출한다.
3. ``_create_service`` (member) factory 가 normal exit 에서 ``Database.close``
   를 호출한다.
4. ``member list`` 경로에서 ``MemberService.initialize`` 가 계속 호출된다
   (#1854 §4.2 예외 — schema DDL 보존).
5. ``approval list`` factory 가 ``ApprovalService.initialize`` 실패 시
   ``Database.close`` 를 호출한다 (#1755 회귀 lock).
6. ``approval audit-types`` factory 가 ``ApprovalService.initialize`` 실패 시
   ``Database.close`` 를 호출한다 (#1755 회귀 lock).
7. ``approval info`` factory 가 ``_find_request`` 실패 시 ``Database.close``
   를 호출한다 (#1755 회귀 lock).
8. ``approval review`` factory 가 ``service.add_review`` 실패 시
   ``Database.close`` 를 호출한다 (#1755 회귀 lock).
9. ``approval`` 4 commands 의 ``--db-path`` override 가 보존되어 ``Database``
   생성자에 전달된다 (offline-factory.md §1.1).
10. account factory path 가 변환 전 동일 ``initialize()`` 호출 sequence /
    yielded service 인스턴스 동일성을 보존한다.

invariant: 내부 필드 (``_writer``/``_reader``) 직접 접근 금지 — public
lifecycle method (``Database.close``, ``Service.initialize``) 호출 사실로만
검증한다 (#1722 R3 패턴).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import click
import pytest
from cryptography.fernet import Fernet

from ante.cli.commands import approval as approval_module
from ante.cli.commands.account import _create_account_service
from ante.cli.commands.member import _create_service as _create_member_service
from ante.cli.main import cli
from ante.core.database import Database


def _make_ctx(config_dir: Path) -> click.Context:
    return click.Context(cli, obj={"config_dir": config_dir})


def _bootstrap_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "cfg"
    (config_dir / "db").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return config_dir


# ────────────────────────────────────────────────────────────────────
# Test 1 — account factory closes DB on normal exit
# ────────────────────────────────────────────────────────────────────


class TestAccountFactoryNormalExitCloses:
    @pytest.mark.asyncio
    async def test_account_factory_closes_db_on_normal_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1) normal exit path 에서 ``Database.close`` 가 정확히 1회 호출된다."""
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService

        async def noop_connect(self: Database) -> None:
            return None

        async def noop_initialize(self: AccountService) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(AccountService, "initialize", noop_initialize)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_account_service(ctx) as svc:
                assert isinstance(svc, AccountService)

        assert close_mock.await_count == 1, (
            f"normal exit 에서 Database.close 가 1회 await 되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# Test 2 — account factory closes DB on exception
# ────────────────────────────────────────────────────────────────────


class TestAccountFactoryExceptionCloses:
    @pytest.mark.asyncio
    async def test_account_factory_closes_db_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2) ``AccountService.initialize`` raise 시 ``Database.close`` 1회 호출.

        #1722 회귀 lock — initialize 도중 ``EncryptionKeyMissingError`` 등으로
        실패해도 aiosqlite leak 이 발생하지 않아야 한다.
        """
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.crypto import EncryptionKeyMissingError
        from ante.account.service import AccountService

        async def noop_connect(self: Database) -> None:
            return None

        async def raising_initialize(self: AccountService) -> None:
            raise EncryptionKeyMissingError("simulated key missing")

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(AccountService, "initialize", raising_initialize)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            with pytest.raises(EncryptionKeyMissingError):
                async with _create_account_service(ctx) as _svc:
                    pass  # pragma: no cover

        assert close_mock.await_count == 1, (
            f"initialize 실패 시 Database.close 가 1회 await 되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# Test 3 — member factory closes DB on normal exit
# ────────────────────────────────────────────────────────────────────


class TestMemberFactoryNormalExitCloses:
    @pytest.mark.asyncio
    async def test_member_factory_closes_db_on_normal_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3) member factory normal exit path 에서 ``Database.close`` 1회 호출."""
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.member.service import MemberService

        async def noop_connect(self: Database) -> None:
            return None

        async def noop_initialize(self: MemberService) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(MemberService, "initialize", noop_initialize)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_member_service(ctx) as svc:
                assert isinstance(svc, MemberService)

        assert close_mock.await_count == 1, (
            f"normal exit 에서 Database.close 가 1회 await 되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# Test 4 — member list 경로에서 initialize 가 호출된다 (§4.2 예외)
# ────────────────────────────────────────────────────────────────────


class TestMemberFactoryInitializeForListExceptionPreserved:
    @pytest.mark.asyncio
    async def test_member_factory_initialize_still_called_for_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """4) ``member list`` 경로 (read-only) 에서도 ``MemberService.initialize``
        가 호출된다 — #1854 §4.2 예외 (schema DDL 보존).
        """
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.member.service import MemberService

        async def noop_connect(self: Database) -> None:
            return None

        init_calls: list[int] = []

        async def counting_initialize(self: MemberService) -> None:
            init_calls.append(1)

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(MemberService, "initialize", counting_initialize)

        with patch.object(Database, "close", new_callable=AsyncMock):
            async with _create_member_service(ctx) as _svc:
                pass

        assert len(init_calls) == 1, (
            f"MemberService.initialize 는 read-only 경로에서도 1회 호출되어야 "
            f"한다 (#1854 §4.2 예외) — 실제 호출 수={len(init_calls)}"
        )


# ────────────────────────────────────────────────────────────────────
# Tests 5-8 — approval 4 callsite cleanup on exception (#1755 회귀 lock)
# ────────────────────────────────────────────────────────────────────


async def _run_approval_pattern(
    *,
    config_dir: Path,
    db_path: str | None,
    initialize_should_raise: Exception | None = None,
    list_should_raise: Exception | None = None,
) -> None:
    """approval 4 commands 의 factory 패턴을 직접 재현해 cleanup invariant 만
    검증한다.

    ``open_cli_db(ctx, db_path_override=db_path)`` 활용은 4 명령 모두 동형이므로
    1개 헬퍼로 표현한다. 본 헬퍼는 ``approval list/audit-types/info/review``
    callsite 의 핵심 lifecycle 만 재현한다.
    """
    from ante.approval import ApprovalService
    from ante.cli.db_context import open_cli_db
    from ante.eventbus.bus import EventBus

    async def fake_initialize(self: ApprovalService) -> None:
        if initialize_should_raise is not None:
            raise initialize_should_raise

    async def fake_list_approvals(self: ApprovalService, **kwargs: object) -> list:
        if list_should_raise is not None:
            raise list_should_raise
        return []

    with (
        patch.object(ApprovalService, "initialize", new=fake_initialize),
        patch.object(ApprovalService, "list_approvals", new=fake_list_approvals),
    ):
        ctx = _make_ctx(config_dir)
        async with open_cli_db(ctx, db_path_override=db_path) as db:
            eventbus = EventBus()
            service = ApprovalService(db=db, eventbus=eventbus)
            await service.initialize()
            await service.list_approvals()


class TestApprovalListFactoryClosesOnException:
    @pytest.mark.asyncio
    async def test_approval_list_factory_closes_db_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5) approval list factory: initialize 실패 시 Database.close 1회 호출.

        #1755 회귀 lock — 이전 구현은 close 미도달로 aiosqlite leak 8s busy_timeout
        대기 (probe timeout exit 124). ``open_cli_db`` 헬퍼가 ``BaseException``
        catch + close 보장으로 회귀를 차단한다.
        """
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)

        async def noop_connect(self: Database) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)

        class _SimulatedInitError(RuntimeError):
            pass

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            with pytest.raises(_SimulatedInitError):
                await _run_approval_pattern(
                    config_dir=config_dir,
                    db_path=None,
                    initialize_should_raise=_SimulatedInitError("boom"),
                )

        assert close_mock.await_count == 1


class TestApprovalAuditTypesFactoryClosesOnException:
    @pytest.mark.asyncio
    async def test_approval_audit_types_factory_closes_db_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """6) approval audit-types factory: initialize 실패 → close 1회 (#1755)."""
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)

        async def noop_connect(self: Database) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)

        class _SimulatedError(RuntimeError):
            pass

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            with pytest.raises(_SimulatedError):
                await _run_approval_pattern(
                    config_dir=config_dir,
                    db_path=None,
                    initialize_should_raise=_SimulatedError("boom"),
                )

        assert close_mock.await_count == 1


class TestApprovalInfoFactoryClosesOnException:
    @pytest.mark.asyncio
    async def test_approval_info_factory_closes_db_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """7) approval info factory: ``_find_request`` 실패 → close 1회 (#1755)."""
        from ante.approval import ApprovalService
        from ante.cli.db_context import open_cli_db
        from ante.eventbus.bus import EventBus

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)

        async def noop_connect(self: Database) -> None:
            return None

        async def noop_initialize(self: ApprovalService) -> None:
            return None

        async def raising_find_request(service: object, id: str) -> object:
            raise ValueError("simulated not-found")

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(ApprovalService, "initialize", noop_initialize)
        monkeypatch.setattr(approval_module, "_find_request", raising_find_request)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            ctx = _make_ctx(config_dir)
            with pytest.raises(ValueError, match="simulated not-found"):
                async with open_cli_db(ctx, db_path_override=None) as db:
                    eventbus = EventBus()
                    service = ApprovalService(db=db, eventbus=eventbus)
                    await service.initialize()
                    await approval_module._find_request(service, "missing")

        assert close_mock.await_count == 1


class TestApprovalReviewFactoryClosesOnException:
    @pytest.mark.asyncio
    async def test_approval_review_factory_closes_db_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """8) approval review factory: ``service.add_review`` 실패 → close 1회
        (#1755).
        """
        from ante.approval import ApprovalService
        from ante.cli.db_context import open_cli_db
        from ante.eventbus.bus import EventBus

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)

        async def noop_connect(self: Database) -> None:
            return None

        async def noop_initialize(self: ApprovalService) -> None:
            return None

        async def raising_add_review(self: ApprovalService, **kwargs: object) -> None:
            raise ValueError("simulated invalid id")

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(ApprovalService, "initialize", noop_initialize)
        monkeypatch.setattr(ApprovalService, "add_review", raising_add_review)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            ctx = _make_ctx(config_dir)
            with pytest.raises(ValueError, match="simulated invalid id"):
                async with open_cli_db(ctx, db_path_override=None) as db:
                    eventbus = EventBus()
                    service = ApprovalService(db=db, eventbus=eventbus)
                    await service.initialize()
                    await service.add_review(
                        id="x", reviewer="r", result="pass", detail=""
                    )

        assert close_mock.await_count == 1


# ────────────────────────────────────────────────────────────────────
# Test 9 — --db-path override preservation (offline-factory.md §1.1)
# ────────────────────────────────────────────────────────────────────


class TestApprovalDbPathOverridePreserved:
    @pytest.mark.asyncio
    async def test_approval_db_path_override_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """9) approval 4 commands 의 ``--db-path`` override 가 보존되어
        ``Database(db_path_override)`` 로 전달된다.

        offline-factory.md §1.1: factory 는 Click option parsing 을 직접 수행
        하지 않으며, caller 가 산출한 경로를 입력으로 받는다.
        ``open_cli_db(ctx, db_path_override=...)`` 가 그 인자를 ``Database`` 에
        그대로 forward 한다.
        """
        from ante.cli.db_context import open_cli_db

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        # ctx 의 기본 resolution 과 다른 명시 경로 — override 가 실제로
        # ``Database`` 생성자에 전달되었는지 검증한다.
        override_path = str(tmp_path / "explicit-override.db")

        with patch("ante.cli.db_context.Database") as db_cls:
            instance = db_cls.return_value
            instance.connect = AsyncMock()
            instance.close = AsyncMock()
            async with open_cli_db(ctx, db_path_override=override_path):
                pass

        db_cls.assert_called_once_with(override_path)

        # 추가 검증: ``db_path_override=None`` 은 ``get_db_path(ctx)`` resolution
        # 으로 fallback 된다 — 이는 사용자가 ``--db-path`` 를 미지정한 경로.
        expected_default_db_path = str(config_dir / "db" / "ante.db")
        with patch("ante.cli.db_context.Database") as db_cls2:
            instance2 = db_cls2.return_value
            instance2.connect = AsyncMock()
            instance2.close = AsyncMock()
            async with open_cli_db(ctx, db_path_override=None):
                pass
        db_cls2.assert_called_once_with(expected_default_db_path)


# ────────────────────────────────────────────────────────────────────
# Test 10 — business behavior preservation (factory path yields equivalent svc)
# ────────────────────────────────────────────────────────────────────


class TestFactoryPathPreservesBusinessBehavior:
    @pytest.mark.asyncio
    async def test_factory_path_preserves_business_behavior(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """10) factory path 변환 전후 동일 ``initialize()`` 호출 sequence /
        yielded service 인스턴스 동일성을 보존한다.

        ``_create_account_service`` 는 ``open_cli_db`` 활용 후에도 동일하게
        ``AccountService`` 인스턴스를 yield 하며 ``initialize()`` 를 1회 호출
        한다 (legacy ``await _create_account_service()`` 의 ``svc.initialize``
        호출 횟수와 동형).
        """
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService

        async def noop_connect(self: Database) -> None:
            return None

        init_calls: list[int] = []

        async def counting_initialize(self: AccountService) -> None:
            init_calls.append(1)

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(AccountService, "initialize", counting_initialize)

        captured_svc: AccountService | None = None
        with patch.object(Database, "close", new_callable=AsyncMock):
            async with _create_account_service(ctx) as svc:
                captured_svc = svc

        assert captured_svc is not None
        assert isinstance(captured_svc, AccountService)
        assert len(init_calls) == 1, (
            f"factory 경로에서 AccountService.initialize 는 1회 호출되어야 한다 "
            f"(실제={len(init_calls)})"
        )


# ════════════════════════════════════════════════════════════════════════
# #1857 추가 — 9 domain × cleanup invariant + business behavior parity.
#
# 11~25) bot/config/strategy/system/rule/trade/treasury 7 domain helper +
# audit/report inline 의 ``open_cli_db`` 기반 lifecycle 회귀 lock.
# ════════════════════════════════════════════════════════════════════════


class TestBotServicesFactoryClosesDb:
    """11) ``bot._create_services`` 가 normal exit 에서 ``Database.close`` 호출."""

    @pytest.mark.asyncio
    async def test_bot_services_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService
        from ante.bot.manager import BotManager
        from ante.cli.commands.bot import _create_services

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(AccountService, "initialize", noop)
        monkeypatch.setattr(BotManager, "initialize", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_services(ctx=ctx) as (db, eventbus, manager, svc):
                assert isinstance(svc, AccountService)
                assert isinstance(manager, BotManager)

        assert close_mock.await_count == 1


class TestBotServicesFactoryExceptionCloses:
    """12) ``bot._create_services`` 가 service init 실패 시에도 close 호출."""

    @pytest.mark.asyncio
    async def test_bot_services_exception_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService
        from ante.bot.manager import BotManager
        from ante.cli.commands.bot import _create_services

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        async def raising_initialize(self: BotManager) -> None:
            raise RuntimeError("bot init failed")

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(AccountService, "initialize", noop)
        monkeypatch.setattr(BotManager, "initialize", raising_initialize)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            with pytest.raises(RuntimeError, match="bot init failed"):
                async with _create_services(ctx=ctx):
                    pass

        assert close_mock.await_count == 1


class TestConfigServicesFactoryClosesDb:
    """13) ``config._create_services`` 가 normal exit 에서 ``Database.close`` 호출."""

    @pytest.mark.asyncio
    async def test_config_services_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.cli.commands.config import _create_services
        from ante.config.dynamic import DynamicConfigService

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(DynamicConfigService, "initialize", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_services(ctx=ctx) as (static_cfg, dynamic, db):
                assert isinstance(dynamic, DynamicConfigService)

        assert close_mock.await_count == 1


class TestStrategyRegistryFactoryClosesDb:
    """14) ``strategy._create_registry`` 가 normal exit 에서 ``Database.close`` 호출."""

    @pytest.mark.asyncio
    async def test_strategy_registry_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.cli.commands.strategy import _create_registry
        from ante.strategy.registry import StrategyRegistry

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(StrategyRegistry, "initialize", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_registry(ctx=ctx) as (registry, db):
                assert isinstance(registry, StrategyRegistry)

        assert close_mock.await_count == 1


class TestSystemServicesFactoryClosesDb:
    """15) ``system._create_services`` (bootstrap) 가 normal exit 에서 close."""

    @pytest.mark.asyncio
    async def test_system_services_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.cli.commands.system import _create_services

        async def noop_connect(self: Database) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_services(ctx=ctx) as (db, eventbus):
                assert db is not None

        assert close_mock.await_count == 1


class TestRuleEngineFactoryClosesDb:
    """16) ``rule._create_rule_engine`` 가 normal exit 에서 ``Database.close`` 호출."""

    @pytest.mark.asyncio
    async def test_rule_engine_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.cli.commands.rule import _create_rule_engine
        from ante.rule.engine import RuleEngine

        async def noop_connect(self: Database) -> None:
            return None

        async def existing_account_row(self: Database, sql: str, params: tuple = ()):
            return {"1": 1}

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(Database, "fetch_one", existing_account_row)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_rule_engine("acc-1", ctx=ctx) as (engine, db):
                assert isinstance(engine, RuleEngine)

        assert close_mock.await_count == 1


class TestTradeServiceFactoryClosesDb:
    """17) ``trade._create_trade_service`` 가 normal exit 에서 close."""

    @pytest.mark.asyncio
    async def test_trade_service_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.cli.commands.trade import _create_trade_service
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(PositionHistory, "initialize", noop)
        monkeypatch.setattr(TradeRecorder, "initialize", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_trade_service(ctx=ctx) as (svc, db):
                assert isinstance(svc, TradeService)

        assert close_mock.await_count == 1


class TestTreasuryFactoryClosesDb:
    """18) ``treasury._create_treasury`` 가 normal exit 에서 ``Database.close`` 호출."""

    @pytest.mark.asyncio
    async def test_treasury_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from unittest.mock import MagicMock

        from ante.account.service import AccountService
        from ante.cli.commands.treasury import _create_treasury
        from ante.treasury.treasury import Treasury

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        async def passing_initialize(self: AccountService) -> None:
            return None

        async def returning_account(self: AccountService, account_id: str):
            fake = MagicMock()
            fake.account_id = account_id
            fake.currency = "KRW"
            from decimal import Decimal

            fake.buy_commission_rate = Decimal("0.00015")
            fake.sell_commission_rate = Decimal("0.00015")
            return fake

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(AccountService, "initialize", passing_initialize)
        monkeypatch.setattr(AccountService, "get", returning_account)
        monkeypatch.setattr(Treasury, "initialize", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_treasury("acc-1", ctx=ctx) as (t, db):
                assert isinstance(t, Treasury)

        assert close_mock.await_count == 1


class TestTreasuryManagerFactoryClosesDb:
    """19) ``treasury._create_treasury_manager`` 가 normal exit 에서 close."""

    @pytest.mark.asyncio
    async def test_treasury_manager_normal_exit_closes_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService
        from ante.cli.commands.treasury import _create_treasury_manager
        from ante.treasury.manager import TreasuryManager

        async def noop(*a, **k):  # noqa: ANN001, ANN202
            return None

        async def empty_accounts(self: AccountService, status=None):  # noqa: ANN001
            return []

        monkeypatch.setattr(Database, "connect", noop)
        monkeypatch.setattr(AccountService, "initialize", noop)
        monkeypatch.setattr(AccountService, "list", empty_accounts)
        monkeypatch.setattr(TreasuryManager, "initialize_all", noop)

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            async with _create_treasury_manager(ctx=ctx) as (manager, db):
                assert isinstance(manager, TreasuryManager)

        assert close_mock.await_count == 1


class TestOpenCliDbDbPathOverride:
    """20) ``open_cli_db`` 가 ``db_path_override`` 를 ``Database`` 에 전달한다.

    instrument list/sync/search/import 의 ``--db-path`` Click option 보존
    (offline-factory.md §1.1).
    """

    @pytest.mark.asyncio
    async def test_db_path_override_forwarded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ante.cli.db_context import open_cli_db

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        override_path = str(tmp_path / "override-instrument.db")

        with patch("ante.cli.db_context.Database") as db_cls:
            instance = db_cls.return_value
            instance.connect = AsyncMock()
            instance.close = AsyncMock()
            async with open_cli_db(ctx, db_path_override=override_path):
                pass

        db_cls.assert_called_once_with(override_path)


class TestOpenCliDbCtxResolution:
    """21) ``open_cli_db`` 가 ``db_path_override=None`` 일 때 ctx-기반
    ``get_db_path`` 로 resolution 한다 (기본 경로).
    """

    @pytest.mark.asyncio
    async def test_db_path_default_uses_get_db_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ante.cli.db_context import open_cli_db

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        expected_default_db_path = str(config_dir / "db" / "ante.db")

        with patch("ante.cli.db_context.Database") as db_cls:
            instance = db_cls.return_value
            instance.connect = AsyncMock()
            instance.close = AsyncMock()
            async with open_cli_db(ctx):
                pass

        db_cls.assert_called_once_with(expected_default_db_path)


class TestBotServicesBusinessBehaviorParity:
    """22) ``bot._create_services`` 변환 전후 동일 ``initialize()`` 호출 sequence
    + 동일 service 인스턴스 yield (Codex v1 condition 5 business behavior
    parity).
    """

    @pytest.mark.asyncio
    async def test_bot_services_business_behavior_parity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        from ante.account.service import AccountService
        from ante.bot.manager import BotManager
        from ante.cli.commands.bot import _create_services

        async def noop_connect(self: Database) -> None:
            return None

        init_calls: list[str] = []

        async def acc_init(self: AccountService) -> None:
            init_calls.append("account")

        async def mgr_init(self: BotManager) -> None:
            init_calls.append("bot")

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(AccountService, "initialize", acc_init)
        monkeypatch.setattr(BotManager, "initialize", mgr_init)

        captured: tuple | None = None
        with patch.object(Database, "close", new_callable=AsyncMock):
            async with _create_services(ctx=ctx) as composed:
                captured = composed

        assert captured is not None
        db, eventbus, manager, svc = captured
        # 변환 전후 동일 호출 sequence (account 가 먼저 init, 그 다음 bot manager).
        assert init_calls == ["account", "bot"], init_calls
        assert isinstance(svc, AccountService)
        assert isinstance(manager, BotManager)


class TestTreasuryFactoryRejectsInvalidAccountId:
    """23) ``treasury._create_treasury`` 가 ``invalid account_id`` 를
    ``open_cli_db`` 진입 이전에 거부한다 (resource 미획득).
    """

    @pytest.mark.asyncio
    async def test_invalid_account_id_no_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ante.account.errors import InvalidAccountIdError
        from ante.cli.commands.treasury import _create_treasury

        config_dir = _bootstrap_config_dir(tmp_path, monkeypatch)
        ctx = _make_ctx(config_dir)

        with patch.object(Database, "connect", new_callable=AsyncMock) as connect_mock:
            with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
                with pytest.raises(InvalidAccountIdError):
                    async with _create_treasury("default", ctx=ctx):
                        pass

        # invalid 거부 시점에 db.connect 자체가 호출되지 않는다.
        connect_mock.assert_not_awaited()
        close_mock.assert_not_awaited()
