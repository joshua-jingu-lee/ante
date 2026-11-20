"""Active-order readiness gate helpers (D-ACC-09 축 ii).

3계층 defense-in-depth(RuleEngine 계층1 / Treasury 계층2 / APIGateway 계층3 +
VirtualExecutor G9 backstop)가 공유하는 SSOT 헬퍼다. 각 계층은
``RuntimeReadinessRegistry``(축 i)를 **매 이벤트 시점** 조회(상태 캐시 금지,
G5 liveness)하고, fail-closed(registry 미주입·조회 예외·account 메타 취득 실패 =
차단, G2)로 동작한다.

본 모듈은 reader(gateway/RuleEngine/Treasury/VirtualExecutor)가 공통으로 쓰는:

- ``account_not_ready`` reason 토큰 SSOT(broker-adapter/11-order-flow.md:82) +
  missing-flag suffix 산출(``not_ready_reason``).
- ``account_suspended`` reason 토큰(G7 — 계층1 kill-switch 합성).
- 운영자 가시성 ``NotificationEvent(level=error, category=system)`` 빌더(G6 — 전
  계층 통일 1회, BUY/SELL 무관). 청산(liquidation) SELL marker 검출 시 전용 문구
  (rule-engine/07:91~95, treasury/05:73).
- 청산 marker(machine-readable ASCII prefix — 한국어 reason 매칭 금지)
  부착/검출 헬퍼(``LIQUIDATION_REASON_PREFIX``, ``is_liquidation_reason``).
- fail-closed readiness 평가(``active_trading_blocked``).

scope: 이 헬퍼는 active-order gate reader 전용이다. registry 를 채우는 단일 mark
경로는 ``main._init_*`` 단독이다(D-ACC-09 §3).
"""

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

    - ``account_service is None``(status 소스 미구성, 비게이트 레거시) → ``None``
      (status 축 비활성, 과차단 회피 — 기존 비게이트 동작 보존).
    - 소스 present + ``fetch_failed``(live 조회 예외) 또는 fetched None/status 미상
      → ``STATUS_UNAVAILABLE`` sentinel(**검증 불가** — 스냅샷 fallback 금지, 호출자
      fail-closed 거부).
    - 소스 present + 조회 성공 + status present → **verified status**(SUSPENDED/
      ACTIVE 등) 그대로.

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

    반환 3-state 는 ``derive_account_status`` 와 동일하다:

    - ``account_service is None`` → ``None``(status 축 비활성).
    - 소스 present + ``get`` 예외/None/status 미상 → ``STATUS_UNAVAILABLE``.
    - 소스 present + 조회 성공 + status present → verified status.

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

    **fail-closed reason**: ``registry.is_ready``(또는 면제 평가)가
    예외를 던지면 suffix 를 비우고 bare ``account_not_ready`` 를 반환한다 — 예외를
    호출자로 **전파하지 않는다**. ``active_trading_blocked`` 가 이미 예외=차단
    (fail-closed, G2)으로 끝나는데, 이어지는 reason 산출이 같은 예외(``is_ready``
    재호출)를 흘리면 차단 분기에서 reason 을 만들다 예외가 핸들러 밖으로 새어,
    계층1/2(특히 Treasury)에서 EventBus(bus.py:96)가 그 예외를 swallow 해
    OrderRejectedEvent/NotificationEvent 가 미발행되고 주문이 terminal 없이
    사라진다. reason 도 동일하게 안전값(bare reason)으로 끝내 차단 경로의 terminal
    발행을 보장한다(G2 fail-closed·G6 알림 1회).
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
