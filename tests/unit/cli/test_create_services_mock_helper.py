"""CLI factory mock helper 의 contract lock (#1900).

각 helper가 production factory의 호출 시그니처/yield shape/lifecycle을
정확히 모사하는지 검증한다. helper가 drift하면 본 모듈이 즉시 FAIL하여
sweep 대상 테스트가 stale mock으로 통과하는 사고를 차단한다.

검증 축:

1. ``ctx`` 수신 형태 (positional / kwarg / kwarg-only)
2. ``async with`` lifecycle (``__aenter__``/``__aexit__``) 정상 호출
3. yield 값이 인자로 전달된 그대로 노출
4. ``ctx`` 누락 호출 허용 (production이 ``ctx=None`` default를 가짐)

production 시그니처 정합 (codex review attempt 2 finding 1):

* ``account``/``bot``/``config``/``member``/``strategy``/``system``/``trade``/
  ``treasury_manager`` factory 는 ``ctx: click.Context | None = None`` 이라
  positional + kwarg 양쪽을 모두 허용한다. helper 도 동형 contract를 가진다.
* ``rule._create_rule_engine``/``treasury._create_treasury`` 만 ``*, ctx``
  키워드 전용이다.
"""

from __future__ import annotations

import pytest

from tests.unit.cli.conftest import (
    mock_account_service_factory,
    mock_bot_services_factory,
    mock_config_services_factory,
    mock_member_service_factory,
    mock_rule_engine_factory,
    mock_strategy_registry_factory,
    mock_system_services_factory,
    mock_trade_service_factory,
    mock_treasury_factory,
    mock_treasury_manager_factory,
)

# ── 1. account: positional + kwarg ctx ────────────────────────────────────


@pytest.mark.asyncio
async def test_account_service_factory_positional_ctx_yields_svc() -> None:
    """production: ``async with _create_account_service(ctx) as svc:`` 모사."""
    sentinel = object()
    factory = mock_account_service_factory(sentinel)
    async with factory(None) as svc:
        assert svc is sentinel


@pytest.mark.asyncio
async def test_account_service_factory_kwarg_ctx_yields_svc() -> None:
    """일부 호출처(``_create_account_service(ctx=ctx)``) 호환."""
    sentinel = object()
    factory = mock_account_service_factory(sentinel)
    async with factory(ctx=None) as svc:
        assert svc is sentinel


@pytest.mark.asyncio
async def test_account_service_factory_no_ctx_yields_svc() -> None:
    """``ctx=None`` default 활용 (#1856 R3 회귀 회피)."""
    sentinel = object()
    factory = mock_account_service_factory(sentinel)
    async with factory() as svc:
        assert svc is sentinel


# ── 2. bot: positional + kwarg ctx, 4-tuple yield ─────────────────────────


@pytest.mark.asyncio
async def test_bot_services_factory_kwarg_ctx_yields_4tuple() -> None:
    """production: ``async with _create_services(ctx=ctx) as (db, eb, mgr, svc):``."""
    db, eb, mgr, svc = object(), object(), object(), object()
    factory = mock_bot_services_factory(db, eb, mgr, svc)
    async with factory(ctx=None) as values:
        assert values == (db, eb, mgr, svc)


@pytest.mark.asyncio
async def test_bot_services_factory_positional_ctx_yields_4tuple() -> None:
    """production이 ``ctx: click.Context | None = None`` 이라 positional 도 허용.

    (codex review attempt 2 finding 1: helper 가 kwarg-only 로 막으면 잘못된
    contract lock.)
    """
    db, eb, mgr, svc = object(), object(), object(), object()
    factory = mock_bot_services_factory(db, eb, mgr, svc)
    async with factory(None) as values:
        assert values == (db, eb, mgr, svc)


@pytest.mark.asyncio
async def test_bot_services_factory_no_ctx_yields_4tuple() -> None:
    """``ctx=None`` default 활용 (인자 없이 호출)."""
    db, eb, mgr, svc = object(), object(), object(), object()
    factory = mock_bot_services_factory(db, eb, mgr, svc)
    async with factory() as values:
        assert values == (db, eb, mgr, svc)


# ── 3. config: positional + kwarg ctx, 3-tuple yield ──────────────────────


@pytest.mark.asyncio
async def test_config_services_factory_yields_3tuple() -> None:
    """production: ``async with _create_services(ctx=ctx) as (static, dyn, db):``."""
    static, dyn, db = object(), object(), object()
    factory = mock_config_services_factory(static, dyn, db)
    async with factory(ctx=None) as values:
        assert values == (static, dyn, db)


@pytest.mark.asyncio
async def test_config_services_factory_positional_ctx_yields_3tuple() -> None:
    """production positional ctx 허용 (codex review attempt 2 finding 1)."""
    static, dyn, db = object(), object(), object()
    factory = mock_config_services_factory(static, dyn, db)
    async with factory(None) as values:
        assert values == (static, dyn, db)


# ── 4. member: positional ctx, single yield ──────────────────────────────


@pytest.mark.asyncio
async def test_member_service_factory_positional_ctx() -> None:
    """production: ``async with _create_service(ctx) as service:``."""
    sentinel = object()
    factory = mock_member_service_factory(sentinel)
    async with factory(None) as svc:
        assert svc is sentinel


# ── 5. rule: account_id positional + ctx kwarg-only ──────────────────────


@pytest.mark.asyncio
async def test_rule_engine_factory_account_id_positional_ctx_kwarg() -> None:
    """production: ``async with _create_rule_engine(acc, ctx=ctx) as (engine, db):``."""
    engine, db = object(), object()
    factory = mock_rule_engine_factory(engine, db)
    async with factory("acc-1", ctx=None) as values:
        assert values == (engine, db)


@pytest.mark.asyncio
async def test_rule_engine_factory_rejects_ctx_positional() -> None:
    """ctx는 kwarg-only (production의 ``*, ctx=None``)."""
    factory = mock_rule_engine_factory(None, None)
    with pytest.raises(TypeError):
        async with factory("acc-1", None):
            pass


# ── 6. strategy: positional + kwarg ctx, 2-tuple yield ───────────────────


@pytest.mark.asyncio
async def test_strategy_registry_factory_yields_2tuple() -> None:
    """production: ``async with _create_registry(ctx=ctx) as (registry, db):``."""
    registry, db = object(), object()
    factory = mock_strategy_registry_factory(registry, db)
    async with factory(ctx=None) as values:
        assert values == (registry, db)


@pytest.mark.asyncio
async def test_strategy_registry_factory_positional_ctx_yields_2tuple() -> None:
    """production positional ctx 허용 (codex review attempt 2 finding 1)."""
    registry, db = object(), object()
    factory = mock_strategy_registry_factory(registry, db)
    async with factory(None) as values:
        assert values == (registry, db)


# ── 7. system: positional + kwarg ctx, 2-tuple yield ─────────────────────


@pytest.mark.asyncio
async def test_system_services_factory_yields_2tuple() -> None:
    """production: ``async with _create_services(ctx=ctx) as (db, eventbus):``."""
    db, eb = object(), object()
    factory = mock_system_services_factory(db, eb)
    async with factory(ctx=None) as values:
        assert values == (db, eb)


@pytest.mark.asyncio
async def test_system_services_factory_positional_ctx_yields_2tuple() -> None:
    """production positional ctx 허용 (codex review attempt 2 finding 1)."""
    db, eb = object(), object()
    factory = mock_system_services_factory(db, eb)
    async with factory(None) as values:
        assert values == (db, eb)


# ── 8. trade: positional + kwarg ctx, 2-tuple yield ──────────────────────


@pytest.mark.asyncio
async def test_trade_service_factory_yields_2tuple() -> None:
    """production: ``async with _create_trade_service(ctx=ctx) as (svc, db):``."""
    svc, db = object(), object()
    factory = mock_trade_service_factory(svc, db)
    async with factory(ctx=None) as values:
        assert values == (svc, db)


@pytest.mark.asyncio
async def test_trade_service_factory_positional_ctx_yields_2tuple() -> None:
    """production positional ctx 허용 (codex review attempt 2 finding 1)."""
    svc, db = object(), object()
    factory = mock_trade_service_factory(svc, db)
    async with factory(None) as values:
        assert values == (svc, db)


# ── 9. treasury (single): account_id positional + ctx kwarg ──────────────


@pytest.mark.asyncio
async def test_treasury_factory_account_id_positional() -> None:
    """production: ``async with _create_treasury(acc, ctx=ctx) as (t, db):``."""
    treasury, db = object(), object()
    factory = mock_treasury_factory(treasury, db)
    async with factory("acc-1", ctx=None) as values:
        assert values == (treasury, db)


@pytest.mark.asyncio
async def test_treasury_factory_no_account_id_default_none() -> None:
    """``account_id=None`` default 활용."""
    treasury, db = object(), object()
    factory = mock_treasury_factory(treasury, db)
    async with factory(ctx=None) as values:
        assert values == (treasury, db)


# ── 10. treasury manager: positional + kwarg ctx ─────────────────────────


@pytest.mark.asyncio
async def test_treasury_manager_factory_yields_2tuple() -> None:
    """production: ``async with _create_treasury_manager(ctx=ctx) as (mgr, db):``."""
    mgr, db = object(), object()
    factory = mock_treasury_manager_factory(mgr, db)
    async with factory(ctx=None) as values:
        assert values == (mgr, db)


@pytest.mark.asyncio
async def test_treasury_manager_factory_positional_ctx_yields_2tuple() -> None:
    """production positional ctx 허용 (codex review attempt 2 finding 1)."""
    mgr, db = object(), object()
    factory = mock_treasury_manager_factory(mgr, db)
    async with factory(None) as values:
        assert values == (mgr, db)


# ── lifecycle 단언 (모든 helper 공통) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_factory_lifecycle_exit_runs_after_yield() -> None:
    """``async with`` lifecycle: helper 가 ``__aexit__`` 까지 정상 진행."""
    state: list[str] = []

    sentinel = object()
    factory = mock_account_service_factory(sentinel)
    async with factory() as svc:
        state.append("inside")
        assert svc is sentinel
    state.append("outside")

    assert state == ["inside", "outside"]
