"""RuntimeReadinessRegistry 단위 테스트 (#2397 D-ACC-09).

면제 매트릭스(broker_type×trading_mode 분리·virtual/test no-op ready·
treasury_sync 요구), default not_ready(fail-closed), active_trading_ready
derive(AND), mark_ready/mark_not_ready 를 검증한다.
"""

from __future__ import annotations

import pytest

from ante.account.models import TradingMode
from ante.account.readiness import (
    ALL_FLAGS,
    ReadinessFlag,
    RuntimeReadinessRegistry,
    is_flag_exempt,
)

# ── 면제 매트릭스 (D-ACC-09 §4) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("broker_type", "trading_mode", "flag", "expected_exempt"),
    [
        # test/virtual: broker/fill/reconcile 면제, treasury_sync 요구.
        ("test", TradingMode.VIRTUAL, ReadinessFlag.BROKER, True),
        ("test", TradingMode.VIRTUAL, ReadinessFlag.FILL_RECONCILE, True),
        ("test", TradingMode.VIRTUAL, ReadinessFlag.RECONCILE, True),
        ("test", TradingMode.VIRTUAL, ReadinessFlag.TREASURY_SYNC, False),
        # kis-domestic/virtual: 동일 면제 패턴(broker_type 무관, trading_mode 축).
        ("kis-domestic", TradingMode.VIRTUAL, ReadinessFlag.BROKER, True),
        ("kis-domestic", TradingMode.VIRTUAL, ReadinessFlag.FILL_RECONCILE, True),
        ("kis-domestic", TradingMode.VIRTUAL, ReadinessFlag.RECONCILE, True),
        ("kis-domestic", TradingMode.VIRTUAL, ReadinessFlag.TREASURY_SYNC, False),
        # kis-domestic/live: 전부 요구(면제 없음).
        ("kis-domestic", TradingMode.LIVE, ReadinessFlag.BROKER, False),
        ("kis-domestic", TradingMode.LIVE, ReadinessFlag.FILL_RECONCILE, False),
        ("kis-domestic", TradingMode.LIVE, ReadinessFlag.RECONCILE, False),
        ("kis-domestic", TradingMode.LIVE, ReadinessFlag.TREASURY_SYNC, False),
    ],
)
def test_exemption_matrix(
    broker_type: str,
    trading_mode: TradingMode,
    flag: ReadinessFlag,
    expected_exempt: bool,
) -> None:
    """면제 매트릭스가 스펙 표대로 (broker_type, trading_mode)×flag 를 분리한다."""
    assert (
        is_flag_exempt(flag, broker_type=broker_type, trading_mode=trading_mode)
        is expected_exempt
    )


def test_exemption_explicit_pairs_only_fail_closed() -> None:
    """broker/fill/reconcile 면제는 **명시 pair만**(fail-closed).

    (test, virtual)·(kis-domestic, virtual) 만 면제. 미지정/신규 broker_type 은
    virtual 이어도 비면제(요구) — trading_mode 만 보던 fail-open 회귀 방지
    (Codex P2, [must_fix A]). 전 broker_type 의 live 도 비면제.
    """
    bfr = (
        ReadinessFlag.BROKER,
        ReadinessFlag.FILL_RECONCILE,
        ReadinessFlag.RECONCILE,
    )
    for flag in bfr:
        # 명시 면제 pair (virtual) → 면제
        assert is_flag_exempt(
            flag, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        assert is_flag_exempt(
            flag, broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL
        )
        # 미지정/신규 broker_type + virtual → fail-closed(비면제)
        assert not is_flag_exempt(
            flag, broker_type="future-broker", trading_mode=TradingMode.VIRTUAL
        )
        # 전 broker_type 의 live → 비면제(요구)
        for bt in ("test", "kis-domestic", "future-broker"):
            assert not is_flag_exempt(
                flag, broker_type=bt, trading_mode=TradingMode.LIVE
            )


def test_unknown_pair_fail_closed() -> None:
    """매트릭스 미지정 미래 (broker_type, trading_mode) pair 는 fail-closed.

    미지정 broker_type 도 LIVE 면 전 플래그 요구(비면제)다.
    """
    for flag in ALL_FLAGS:
        assert not is_flag_exempt(
            flag, broker_type="ibkr", trading_mode=TradingMode.LIVE
        )


# ── default not_ready (fail-closed) ────────────────────────────────────────


def test_default_not_ready_fail_closed() -> None:
    """명시 mark 이전 모든 플래그는 not_ready(디폴트 fail-closed)."""
    reg = RuntimeReadinessRegistry()
    for flag in ALL_FLAGS:
        assert reg.is_ready("acc", flag) is False
    # 미등록 계좌의 not_ready_flags 는 전 플래그.
    assert reg.not_ready_flags("never-seen") == list(ALL_FLAGS)


def test_default_live_account_not_active_trading_ready() -> None:
    """LIVE 계좌는 명시 mark 전 active_trading_ready=False(fail-closed)."""
    reg = RuntimeReadinessRegistry()
    assert (
        reg.active_trading_ready(
            "live", broker_type="kis-domestic", trading_mode=TradingMode.LIVE
        )
        is False
    )


# ── mark_ready / mark_not_ready ─────────────────────────────────────────────


def test_mark_ready_and_not_ready_roundtrip() -> None:
    """mark_ready/mark_not_ready 가 상태·사유를 정확히 전이한다."""
    reg = RuntimeReadinessRegistry()

    reg.mark_not_ready("acc", ReadinessFlag.BROKER, "EGW00133")
    assert reg.is_ready("acc", ReadinessFlag.BROKER) is False
    assert reg.get_reason("acc", ReadinessFlag.BROKER) == "EGW00133"

    reg.mark_ready("acc", ReadinessFlag.BROKER)
    assert reg.is_ready("acc", ReadinessFlag.BROKER) is True
    # ready 전이 시 사유는 제거된다.
    assert reg.get_reason("acc", ReadinessFlag.BROKER) is None


def test_per_account_isolation() -> None:
    """한 계좌 mark 가 다른 계좌에 누출되지 않는다."""
    reg = RuntimeReadinessRegistry()
    reg.mark_ready("a", ReadinessFlag.BROKER)
    assert reg.is_ready("a", ReadinessFlag.BROKER) is True
    assert reg.is_ready("b", ReadinessFlag.BROKER) is False


# ── active_trading_ready derive (AND + 면제) ───────────────────────────────


def test_active_trading_ready_live_requires_all_flags() -> None:
    """LIVE 는 4 플래그 전부 ready 여야 active_trading_ready=True (AND)."""
    reg = RuntimeReadinessRegistry()
    flags = list(ALL_FLAGS)
    # 하나씩 ready 로 올리며 마지막 전까지 False.
    for i, flag in enumerate(flags):
        reg.mark_ready("live", flag)
        ready = reg.active_trading_ready(
            "live", broker_type="kis-domestic", trading_mode=TradingMode.LIVE
        )
        assert ready is (i == len(flags) - 1)


def test_active_trading_ready_live_blocked_by_single_not_ready() -> None:
    """LIVE 에서 한 비면제 플래그만 not_ready 여도 active_trading_ready=False."""
    reg = RuntimeReadinessRegistry()
    for flag in ALL_FLAGS:
        reg.mark_ready("live", flag)
    reg.mark_not_ready("live", ReadinessFlag.FILL_RECONCILE, "catch_up_poll_failed")
    assert (
        reg.active_trading_ready(
            "live", broker_type="kis-domestic", trading_mode=TradingMode.LIVE
        )
        is False
    )


def test_active_trading_ready_virtual_only_needs_treasury_sync() -> None:
    """virtual 은 broker/fill/reconcile 면제 — treasury_sync 만 ready 면 OK."""
    reg = RuntimeReadinessRegistry()
    # broker/fill/reconcile 은 명시 mark 가 없어도(면제) active_trading_ready 에
    # 영향을 주지 않는다. 단 treasury_sync 는 요구.
    assert (
        reg.active_trading_ready(
            "v", broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        is False
    ), "treasury_sync 미충족이면 virtual 도 not ready"

    reg.mark_ready("v", ReadinessFlag.TREASURY_SYNC)
    assert (
        reg.active_trading_ready(
            "v", broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        is True
    ), "virtual 은 treasury_sync 만 충족하면 ready(나머지 면제)"


def test_active_trading_ready_virtual_ignores_broker_not_ready() -> None:
    """virtual 은 broker not_ready(예: KIS 장애)여도 면제라 ready 유지.

    단 이 derive 만으로는 0원 체결을 막지 못하며, VirtualExecutor 시장가 가격
    안전(api-gateway.md)과 짝을 이룬다(#2398). 본 PR 은 derive 만 검증한다.
    """
    reg = RuntimeReadinessRegistry()
    reg.mark_ready("v", ReadinessFlag.TREASURY_SYNC)
    reg.mark_not_ready("v", ReadinessFlag.BROKER, "broker_down")
    assert (
        reg.active_trading_ready(
            "v", broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL
        )
        is True
    )


def test_not_ready_flags_tracks_marks() -> None:
    """not_ready_flags 는 명시 mark 기준 not_ready 플래그를 반환한다."""
    reg = RuntimeReadinessRegistry()
    reg.mark_ready("acc", ReadinessFlag.BROKER)
    reg.mark_ready("acc", ReadinessFlag.TREASURY_SYNC)
    pending = reg.not_ready_flags("acc")
    assert ReadinessFlag.BROKER not in pending
    assert ReadinessFlag.TREASURY_SYNC not in pending
    assert ReadinessFlag.FILL_RECONCILE in pending
    assert ReadinessFlag.RECONCILE in pending
