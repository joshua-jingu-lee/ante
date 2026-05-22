"""Bot info enrichment helper — Web API + IPC 공유.

Refs #1712: Web API ``GET /api/bots/{bot_id}`` 와 IPC ``bot.status`` 가
동일한 ``bot`` info 보강 로직(strategy/budget/positions 조인) 을 공유하기
위한 behavior-preserving extraction. Web API 라우트가 in-place 로 수행하던
보강을 그대로 미러한다(응답 shape/field/key 순서 무변경).

설계 원칙:
- FastAPI / HTTPException 의존성을 import 하지 않는다 (Codex Plan Review v2
  advisory). 본 helper 는 순수 도메인 dict 변환만 수행하며, HTTP / IPC 표면
  매핑은 각 라우트/handler 가 담당한다.
- 의존성은 모두 keyword-only optional — 보유한 객체만 보강에 기여한다. None
  이면 해당 섹션은 skip 되며 dict 에 키가 추가되지 않는다(누락 vs. 빈 값
  의미 구분).
- ``trade_service`` 는 #1712 에서 ``ServiceRegistry`` 에 optional 로 도입
  되었다. legacy / cold-path 환경에서 None 이면 ``positions`` 키 자체가
  부재한다(회귀 lock).
"""

from __future__ import annotations

from typing import Any


async def enrich_bot_info(
    bot: Any,
    *,
    strategy_registry: Any | None = None,
    treasury: Any | None = None,
    trade_service: Any | None = None,
) -> dict[str, Any]:
    """``bot.get_info()`` 결과에 strategy/budget/positions 정보를 보강한다.

    Refs #1712: Web API ``GET /api/bots/{bot_id}`` (``src/ante/web/routes/
    bots.py`` ``get_bot``) 의 보강 로직을 그대로 미러한다. 응답 shape/field/
    key 순서를 변경하지 않으며, 의존성 None 시 해당 섹션 키 자체가 부재한다.

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
            이면 ``positions`` 키가 추가되지 않는다(회귀 lock — #1712 cold-path
            / legacy 환경 호환).

    Returns:
        ``bot.get_info()`` base dict + 보강 키 dict. Web API 라우트의 in-place
        dict mutation 결과와 동일하다.
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
    if trade_service is not None:
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
