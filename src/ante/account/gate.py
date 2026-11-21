"""Active-order readiness gate helpers (D-ACC-09 축 ii)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ante.account.readiness import ALL_FLAGS, is_flag_exempt

if TYPE_CHECKING:
    from ante.account.models import TradingMode
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.eventbus.events import NotificationEvent

ACCOUNT_NOT_READY_REASON = "account_not_ready"

ACCOUNT_SUSPENDED_REASON = "account_suspended"

ACCOUNT_STATUS_UNAVAILABLE_REASON = "account_status_unavailable"

STATUS_UNAVAILABLE = object()


def derive_account_status(
    account_service: Any | None,
    fetched: Any | None,
    *,
    fetch_failed: bool,
) -> Any | None:
    """이미 fetch 한 account 로부터 G7 kill-switch status 3-state 를 도출한다(I/O 없음).

    status 는 런타임 가변 kill-switch(``account suspend`` IPC)라 생성시점 스냅샷을
    신뢰하면 안 된다. 계층1(RuleEngine)·계층3(APIGateway)가 **동일** 도출
    로직을 공유하도록(중복 구현 금지) 순수 함수로 추출한다.

    스냅샷 fallback 은 절대 금지한다 — live 조회 실패 시 stale ACTIVE 로 통과하면
    suspended 계좌가 kill-switch 를 우회한다(spec rule-engine/07:88 "조회 예외도
    차단").
    """
    if account_service is None:
        return None
    if fetch_failed or fetched is None:
        return STATUS_UNAVAILABLE
    status = getattr(fetched, "status", None)
    if status is None:
        return STATUS_UNAVAILABLE
    return status


async def resolve_account_status(
    account_service: Any | None,
    account_id: str,
) -> Any | None:
    """G7 — live ``AccountStatus`` 3-state 를 조회·도출한다(공유 SSOT 헬퍼).

    계층1(RuleEngine)·계층3(APIGateway)가 **동일 헬퍼**로 status 축을 평가한다
    (중복 구현 금지). status 는 런타임 가변 kill-switch 라 반드시 **live**
    ``account_service.get`` 로 본다 — 생성시점 스냅샷 fallback 금지.

    호출자는 SUSPENDED → ``account_suspended`` 차단, ``STATUS_UNAVAILABLE`` →
    ``account_status_unavailable`` fail-closed, ``None``/verified non-SUSPENDED →
    status 축 통과로 처리한다.
    """
    if account_service is None:
        return None
    get = getattr(account_service, "get", None)
    if get is None:
        return STATUS_UNAVAILABLE
    try:
        fetched = await get(account_id)
    except Exception:
        return derive_account_status(account_service, None, fetch_failed=True)
    return derive_account_status(account_service, fetched, fetch_failed=False)


LIQUIDATION_REASON_PREFIX = "liquidation:"


def is_liquidation_reason(reason: object) -> bool:
    """``reason`` 이 청산 marker(``liquidation:`` ASCII prefix)를 갖는가."""
    return isinstance(reason, str) and reason.startswith(LIQUIDATION_REASON_PREFIX)


@dataclass(frozen=True)
class GateDecision:
    """readiness gate 평가 결과.

    - ``blocked``: True 면 active-order 거부(fail-closed 포함).
    - ``reason``: 거부 사유 토큰(``account_not_ready: <missing>`` |
      ``account_suspended``). ``blocked`` False 면 ``""``.
    """

    blocked: bool
    reason: str


def not_ready_reason(
    registry: RuntimeReadinessRegistry | None,
    account_id: str,
    *,
    broker_type: str,
    trading_mode: TradingMode,
) -> str:
    """``account_not_ready`` reason + missing-flag suffix 를 산출한다.

    면제 플래그는 제외하고(매트릭스), 비면제이면서 not_ready(또는 registry 미주입)
    인 플래그만 suffix 로 나열한다. registry 가 None 이면(fail-closed) 비면제 전
    플래그를 missing 으로 표기한다.
    """
    try:
        missing: list[str] = []
        for flag in ALL_FLAGS:
            if is_flag_exempt(flag, broker_type=broker_type, trading_mode=trading_mode):
                continue
            if registry is None or not registry.is_ready(account_id, flag):
                missing.append(flag.value)
    except Exception:
        return ACCOUNT_NOT_READY_REASON
    if missing:
        return f"{ACCOUNT_NOT_READY_REASON}: {', '.join(missing)}"
    return ACCOUNT_NOT_READY_REASON


def active_trading_blocked(
    registry: RuntimeReadinessRegistry | None,
    account_id: str,
    *,
    broker_type: str,
    trading_mode: TradingMode,
) -> bool:
    """active-trading 차단 여부(fail-closed, G1/G2).

    - registry 미주입(None) → 차단(fall-open 금지).
    - ``active_trading_ready`` 조회 예외 → 차단.
    - 면제 매트릭스 적용 후 비면제 플래그가 not_ready → 차단.
    """
    if registry is None:
        return True
    try:
        return not registry.active_trading_ready(
            account_id, broker_type=broker_type, trading_mode=trading_mode
        )
    except Exception:
        return True


def build_not_ready_notification(
    *,
    account_id: str,
    reason: str,
    side: object = "",
    is_liquidation: bool = False,
) -> NotificationEvent:
    """not_ready 거부 시 운영자 가시성 ``NotificationEvent`` 빌더(G6).

    전 계층(1/2/3 + G9) 통일 — ``level=error, category=system`` 으로 정확히 1회
    발행한다(BUY/SELL 무관). 청산(liquidation) SELL marker 가 검출되면 "청산 차단"
    전용 문구를 쓰고(rule-engine/07:91~95), 그 외 일반 거부는 generic 문구를 쓴다.
    """
    from ante.eventbus.events import NotificationEvent

    side_str = side if isinstance(side, str) else ""
    if is_liquidation:
        title = "청산 차단: account not_ready — 수동 청산 필요"
        message = (
            f"계좌 {account_id} 의 봇 삭제 청산(SELL) 주문이 readiness not_ready 로 "
            f"거부되었습니다. 봇 삭제는 진행되며 미청산 포지션이 남습니다. "
            f"수동 청산이 필요합니다. (사유: {reason})"
        )
    else:
        side_label = side_str.upper() if side_str else "주문"
        title = "주문 차단: account not_ready"
        message = (
            f"계좌 {account_id} 의 active-order({side_label}) 주문이 readiness "
            f"not_ready 로 거부되었습니다. (사유: {reason})"
        )
    return NotificationEvent(
        level="error",
        title=title,
        message=message,
        category="system",
    )
