"""Bot info enrichment helper — IPC 공유.

IPC ``bot.status`` 가 ``bot`` info 보강 로직 (strategy/budget/positions
조인) 을 공유하기 위한 extraction.

설계 원칙:
- 본 helper 는 순수 도메인 dict 변환만 수행하며, IPC 표면 매핑은 handler가
  담당한다.
- 의존성은 모두 keyword-only optional — 보유한 객체만 보강에 기여한다. None
  이면 해당 섹션은 skip 되며 dict 에 키가 추가되지 않는다(누락 vs. 빈 값
  의미 구분).
- ``trade_service`` 는 ``ServiceRegistry`` 에 optional 로 주입된다.
  legacy / cold-path 환경에서 None 이면 ``positions`` 키 자체가 부재한다
  (회귀 lock).
"""

from __future__ import annotations

from typing import Any


async def enrich_bot_info(
    bot: Any,
    *,
    strategy_registry: Any | None = None,
    treasury: Any | None = None,
    trade_service: Any | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """``bot.get_info()`` 결과에 strategy/budget/positions 정보를 보강한다.

    응답 shape/field/key 순서를 변경하지 않으며, 의존성 None 시 해당 섹션
    키 자체가 부재한다.

    Args:
        bot: ``get_info()`` 메서드를 가진 Bot 인스턴스. info 의 ``strategy_id``
            필드가 strategy 조인의 키로 사용된다.
        strategy_registry: ``StrategyRegistry`` (또는 ``get``/``get_by_name``
            await coroutine 을 노출하는 stub). None 이면 strategy_name /
            strategy_author_* / strategy 키가 추가되지 않는다.
        treasury: 단일 계좌의 ``Treasury`` 인스턴스(``.get_budget(bot_id)``
            sync 메서드 보유). None 이면 ``budget`` 키가 추가되지 않는다.
            IPC 호출 측은 ``svc.treasury_manager.get(bot.config.account_id)``
            로 미리 resolve 한 뒤 전달한다.
        trade_service: ``TradeService`` (또는 ``get_positions(bot_id=...,
            include_closed=...)`` await coroutine 을 노출하는 stub). None
            이면 ``positions`` 키가 추가되지 않는다 (회귀 lock — cold-path
            / legacy 환경 호환).
        account_id: 봇 소속 계좌(``bot.config.account_id``). ``None`` 이 아니면
            (#2137) ``trade_service.get_positions(...)`` 호출에 ``account_id=``
            kwarg 를 추가해 포지션 조회를 봇 계좌로 스코핑한다(타 계좌 stale
            /legacy 포지션 누출 차단). ``None`` 이면 기존 ``get_positions(bot_id=
            ..., include_closed=True)`` call shape 를 그대로 보존한다(legacy
            stub / 미전달 호출처 회귀 lock). 응답 shape 에는 영향을 주지 않는다.

    Returns:
        ``bot.get_info()`` base dict + 보강 키 dict.
    """
    info: dict[str, Any] = bot.get_info()

    # 전략 정보 추가 — strategy_id 미존재(빈 문자열) 시 lookup 자체를 skip.
    if strategy_registry is not None:
        record = await strategy_registry.get(info.get("strategy_id", ""))
        if record:
            info["strategy_name"] = record.name
            info["strategy_author_name"] = record.author_name
            info["strategy_author_id"] = record.author_id
            info["strategy"] = {
                "name": record.name,
                "version": record.version,
                "author_name": record.author_name,
                "author_id": record.author_id,
                "description": record.description,
            }

    # 예산 정보 추가 — Treasury.get_budget 은 sync, 부재 시 None.
    if treasury is not None:
        budget = treasury.get_budget(bot.bot_id)
        if budget:
            info["budget"] = {
                "allocated": budget.allocated,
                "spent": budget.spent,
                "reserved": budget.reserved,
                "available": budget.available,
            }

    # 포지션 정보 추가 — include_closed=True 보존.
    # account_id 가 주어지면(#2137) 봇 계좌로 스코핑해 타 계좌 stale/legacy
    # 포지션 누출을 차단한다. None 이면 기존 call shape 를 그대로 유지한다
    # (legacy stub / 미전달 호출처 회귀 lock).
    if trade_service is not None:
        if account_id is not None:
            positions = await trade_service.get_positions(
                bot_id=bot.bot_id, include_closed=True, account_id=account_id
            )
        else:
            positions = await trade_service.get_positions(
                bot_id=bot.bot_id, include_closed=True
            )
        info["positions"] = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "realized_pnl": p.realized_pnl,
            }
            for p in positions
        ]

    return info
