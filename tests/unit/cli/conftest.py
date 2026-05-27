"""CLI 테스트 공용 async ctxmgr factory mock helper (#1900).

production CLI 명령은 #1855(`open_cli_db`) 도입 이후 모든 factory가 다음
패턴으로 진입한다::

    async with _create_services(ctx=ctx) as (db, eventbus, ...):

mock이 같은 lifecycle을 정확히 모사하지 못하면 두 부류의 회귀가 발생한다:

1. ``ctx=`` kwarg 미수신 → ``TypeError: ... got an unexpected keyword
   argument 'ctx'`` (#1900 회귀 A)
2. plain tuple ``return_value`` → ``'tuple' object does not support the
   asynchronous context manager protocol`` (#1900 회귀 B/E)

본 모듈은 ``src/ante/cli/commands/*.py`` 의 ``@asynccontextmanager`` factory
**10개** 각각을 1:1로 모사하는 헬퍼를 제공한다. 각 헬퍼는:

- ``@asynccontextmanager`` 로 정의되어 ``async with`` lifecycle을 정확히 흉내
- production 호출 시그니처(positional vs kwarg)를 정확히 모사
- yield 값을 인자로 받아 그대로 반환

Census (10 + 1 legacy 제외):

================================================== =======================
Production factory                                  Helper
================================================== =======================
``account._create_account_service(ctx)``            ``mock_account_service_factory``
``bot._create_services(ctx=ctx)``                   ``mock_bot_services_factory``
``config._create_services(ctx=ctx)``                ``mock_config_services_factory``
``member._create_service(ctx)``                     ``mock_member_service_factory``
``rule._create_rule_engine(acc, ctx=ctx)``          ``mock_rule_engine_factory``
``strategy._create_registry(ctx=ctx)``              ``mock_strategy_registry_factory``
``system._create_services(ctx=ctx)``                ``mock_system_services_factory``
``trade._create_trade_service(ctx=ctx)``            ``mock_trade_service_factory``
``treasury._create_treasury(acc, ctx=ctx)``         ``mock_treasury_factory``
``treasury._create_treasury_manager(ctx=ctx)``      ``mock_treasury_manager_factory``
``broker._create_account_service()`` (legacy)       (excluded — #1818 follow-up)
================================================== =======================

본 헬퍼는 ``unittest.mock.patch(..., new=mock_..._factory(yield_value))`` 형태로
factory 자체를 교체한다. 호출자(``async with _create_xxx(...) as value:``)는
production과 동일한 lifecycle을 경험한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import click

__all__ = [
    "mock_account_service_factory",
    "mock_bot_services_factory",
    "mock_config_services_factory",
    "mock_member_service_factory",
    "mock_rule_engine_factory",
    "mock_strategy_registry_factory",
    "mock_system_services_factory",
    "mock_trade_service_factory",
    "mock_treasury_factory",
    "mock_treasury_manager_factory",
]


def mock_account_service_factory(svc: Any):
    """``account._create_account_service`` 모사.

    production: ``async with _create_account_service(ctx) as svc:`` (positional ctx).
    호환을 위해 positional + kwarg 둘 다 수신한다.
    """

    @asynccontextmanager
    async def _factory(
        ctx: click.Context | None = None,
    ) -> AsyncIterator[Any]:
        yield svc

    return _factory


def mock_bot_services_factory(db: Any, eventbus: Any, mgr: Any, account_service: Any):
    """``bot._create_services`` 모사.

    yield: 4-tuple ``(db, eventbus, mgr, account_service)``.
    production: ``async with _create_services(ctx=ctx) as (...)`` (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any, Any, Any]]:
        yield db, eventbus, mgr, account_service

    return _factory


def mock_config_services_factory(static: Any, dynamic: Any, db: Any):
    """``config._create_services`` 모사. 3-tuple yield (static, dynamic, db).

    production: ``async with _create_services(ctx=ctx) as (...)`` (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any, Any]]:
        yield static, dynamic, db

    return _factory


def mock_member_service_factory(svc: Any):
    """``member._create_service`` 모사. svc yield.

    production: ``async with _create_service(ctx) as service:`` (positional ctx).
    """

    @asynccontextmanager
    async def _factory(
        ctx: click.Context | None = None,
    ) -> AsyncIterator[Any]:
        yield svc

    return _factory


def mock_rule_engine_factory(engine: Any, db: Any):
    """``rule._create_rule_engine`` 모사. 2-tuple yield (engine, db).

    production: ``async with _create_rule_engine(account_id, ctx=ctx) as (engine, db):``
    (account_id positional + ctx kwarg-only).
    """

    @asynccontextmanager
    async def _factory(
        account_id: str, *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield engine, db

    return _factory


def mock_strategy_registry_factory(registry: Any, db: Any):
    """``strategy._create_registry`` 모사. 2-tuple yield (registry, db).

    production: ``async with _create_registry(ctx=ctx) as (registry, db):``
    (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield registry, db

    return _factory


def mock_system_services_factory(db: Any, eventbus: Any):
    """``system._create_services`` 모사. 2-tuple yield (db, eventbus).

    production: ``async with _create_services(ctx=ctx) as (db, eventbus):``
    (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield db, eventbus

    return _factory


def mock_trade_service_factory(svc: Any, db: Any):
    """``trade._create_trade_service`` 모사. 2-tuple yield (service, db).

    production: ``async with _create_trade_service(ctx=ctx) as (service, db):``
    (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield svc, db

    return _factory


def mock_treasury_factory(treasury: Any, db: Any):
    """``treasury._create_treasury`` 모사. 2-tuple yield (treasury, db).

    production: ``async with _create_treasury(account_id, ctx=ctx) as (t, db):``
    (account_id positional + ctx kwarg-only).
    """

    @asynccontextmanager
    async def _factory(
        account_id: str | None = None,
        *,
        ctx: click.Context | None = None,
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield treasury, db

    return _factory


def mock_treasury_manager_factory(mgr: Any, db: Any):
    """``treasury._create_treasury_manager`` 모사. 2-tuple yield (manager, db).

    production: ``async with _create_treasury_manager(ctx=ctx) as (manager, db):``
    (kwarg only).
    """

    @asynccontextmanager
    async def _factory(
        *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield mgr, db

    return _factory
