"""RuntimeReadinessRegistry — per-account runtime readiness SSOT (D-ACC-09, #2397).

스펙 SSOT: [docs/specs/account/02-design-decisions.md — D-ACC-09](
../../../docs/specs/account/02-design-decisions.md) ·
[05-eventbus-integration.md](../../../docs/specs/account/05-eventbus-integration.md).

`AccountStatus`(user kill-switch 축)와 **직교**하는 service-health 자동축이다.
주문 가능 여부(``active_trading_ready``)는 broker/treasury_sync/fill/reconcile
스케줄러 등록 성공/실패에서 derive 한다. SSOT 는 본 registry **단독**이며,
``Services.fill_schedulers``/``reconcile_schedulers`` dict 는 스케줄러 인스턴스
보관용일 뿐이다(reader 는 registry 만 조회).

본 PR(#2397)은 registry 를 채우기만 한다(관측-only). active-order gate reader
는 #2398 에서 추가한다 — 따라서 이 모듈을 도입해도 **주문 동작은 불변**이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ante.account.models import TradingMode


class ReadinessFlag(StrEnum):
    """per-account runtime readiness 4 플래그 (D-ACC-09 §2)."""

    BROKER = "broker_ready"
    TREASURY_SYNC = "treasury_sync_ready"
    FILL_RECONCILE = "fill_reconcile_ready"
    RECONCILE = "reconcile_ready"


# active-trading 전제 플래그 전부. ``active_trading_ready`` 는 면제 매트릭스로
# 면제된 플래그를 ``True`` 로 취급한 뒤 이 집합 전체를 AND 한다(D-ACC-09 §2).
ALL_FLAGS: tuple[ReadinessFlag, ...] = (
    ReadinessFlag.BROKER,
    ReadinessFlag.TREASURY_SYNC,
    ReadinessFlag.FILL_RECONCILE,
    ReadinessFlag.RECONCILE,
)


def is_flag_exempt(
    flag: ReadinessFlag,
    *,
    broker_type: str,
    trading_mode: TradingMode,
) -> bool:
    """``(broker_type, trading_mode)`` pair 에서 ``flag`` 가 면제(항상 ready)인가.

    면제 매트릭스 (D-ACC-09 §4, normative). 열: broker / treasury_sync /
    fill_reconcile / reconcile.

    - ``(test, virtual)``        → 면제 / 요구 / 면제 / 면제
    - ``(kis-domestic, virtual)``→ 면제 / 요구 / 면제 / 면제
    - ``(kis-domestic, live)``   → 요구 / 요구 / 요구 / 요구

    분기축:
    - ``broker``/``fill_reconcile``/``reconcile`` 의 면제축은 **trading_mode** 다.
      VIRTUAL 은 broker API 를 미호출(``VirtualExecutor`` 가 가상 체결)하므로
      broker-backed readiness 가 무의미하다 → 면제(항상 ready). LIVE 는 요구.
    - ``treasury_sync`` 는 VIRTUAL(broker=None Trade-DB sync) 도 sync 를 시작하므로
      **trading_mode 무관 항상 요구**다.

    default 정책은 **fail-closed**: 매트릭스에 미지정인 미래 ``(broker_type,
    trading_mode)`` pair 는 모든 플래그를 요구로 취급한다([must_fix A]).
    """
    if flag is ReadinessFlag.TREASURY_SYNC:
        # treasury_sync 는 VIRTUAL/LIVE 양쪽에서 항상 요구다(면제 없음).
        return False

    # broker/fill_reconcile/reconcile: VIRTUAL 만 면제. LIVE(및 미지정 fail-closed)
    # 는 요구. VIRTUAL 은 broker_type(test/kis-domestic) 무관 면제다.
    return trading_mode == TradingMode.VIRTUAL


@dataclass
class _AccountReadiness:
    """단일 계좌의 readiness 상태. 디폴트는 전부 not_ready(fail-closed)."""

    # 명시 ``mark_ready`` 이전에는 모두 not_ready 다(디폴트 fail-closed, §2).
    ready: dict[ReadinessFlag, bool] = field(default_factory=dict)
    # 마지막 not_ready 사유(관측·알림용). flag 가 ready 면 제거된다.
    reasons: dict[ReadinessFlag, str] = field(default_factory=dict)


class RuntimeReadinessRegistry:
    """per-account runtime readiness SSOT (D-ACC-09).

    registry-owned 권위: ``main._init_*`` 등록자가 스케줄러 등록과 **동시에**
    ``mark_ready``/``mark_not_ready(reason)`` 로 명시 기록하는 단일 mark 경로다
    ([must_fix F]). reader(#2398 gateway/RuleEngine/Treasury)는
    ``active_trading_ready`` 만 호출한다.

    면제 매트릭스는 ``active_trading_ready`` derive 시점에 적용한다 — 면제 플래그는
    명시 mark 없이도 ready 로 취급된다. 단 등록자는 면제 계좌에도 no-op ready 를
    명시 mark 하여 관측 일관성(상태 introspection·테스트 회귀 락)을 보장한다.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, _AccountReadiness] = {}

    def _entry(self, account_id: str) -> _AccountReadiness:
        entry = self._accounts.get(account_id)
        if entry is None:
            entry = _AccountReadiness()
            self._accounts[account_id] = entry
        return entry

    def mark_ready(self, account_id: str, flag: ReadinessFlag) -> None:
        """``flag`` 를 ready 로 표시한다(connect/start 성공 시점).

        면제 계좌의 no-op ready mark 도 이 경로를 쓴다.
        """
        entry = self._entry(account_id)
        entry.ready[flag] = True
        entry.reasons.pop(flag, None)

    def mark_not_ready(self, account_id: str, flag: ReadinessFlag, reason: str) -> None:
        """``flag`` 를 not_ready 로 표시한다(connect/start 실패·skip 시점).

        ``reason`` 은 관측·알림용 사유다(예: ``EGW00133``, ``timeout``,
        ``connected_count==0``).
        """
        entry = self._entry(account_id)
        entry.ready[flag] = False
        entry.reasons[flag] = reason

    def is_ready(self, account_id: str, flag: ReadinessFlag) -> bool:
        """단일 ``flag`` 가 명시 ready 인지(디폴트 fail-closed = False).

        면제는 반영하지 않는다(raw mark 조회). 면제 포함 판정은
        ``active_trading_ready`` 를 쓴다.
        """
        entry = self._accounts.get(account_id)
        if entry is None:
            return False
        return entry.ready.get(flag, False)

    def get_reason(self, account_id: str, flag: ReadinessFlag) -> str | None:
        """``flag`` 의 마지막 not_ready 사유(없으면 None)."""
        entry = self._accounts.get(account_id)
        if entry is None:
            return None
        return entry.reasons.get(flag)

    def active_trading_ready(
        self,
        account_id: str,
        *,
        broker_type: str,
        trading_mode: TradingMode,
    ) -> bool:
        """active-trading 전제 플래그 전부의 AND (단일 derive 함수, §2).

        면제 매트릭스로 면제된 플래그는 ``True`` 로 취급한 뒤 AND 한다. 비면제
        플래그는 명시 ready 여야 한다(디폴트 fail-closed → not_ready 면 False).

        본 PR(#2397)은 이 함수를 호출하는 gate reader 를 **추가하지 않는다**
        (gate=#2398). 관측·테스트 용으로만 노출한다(주문 동작 불변).
        """
        for flag in ALL_FLAGS:
            if is_flag_exempt(flag, broker_type=broker_type, trading_mode=trading_mode):
                continue
            if not self.is_ready(account_id, flag):
                return False
        return True

    def not_ready_flags(self, account_id: str) -> list[ReadinessFlag]:
        """현재 not_ready(명시 mark 기준)인 플래그 목록(관측·self-healing 용)."""
        entry = self._accounts.get(account_id)
        if entry is None:
            return list(ALL_FLAGS)
        return [flag for flag in ALL_FLAGS if not entry.ready.get(flag, False)]
