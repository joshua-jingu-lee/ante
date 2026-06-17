"""EGW00133 단일 cadence backoff + readiness reason 보존 테스트 (#2399 T4/T6).

검증:
- startup wrapper(``_connect_broker_with_auth_retry``): EGW00133 흡수 bounded retry
  (≤DEFAULT_MAX_RETRIES_AUTH), 소진 시 TokenRateLimitError 전파, 비-EGW00133 즉시 전파.
- startup connect 루프: 소진 시 not_ready(reason="EGW00133") 구조적 보존(T6).
- self-healing recover: EGW00133 시 not_ready(reason="EGW00133") + TokenRateLimitError
  re-raise(burst break 신호).
- self-healing burst loop: persistent EGW00133 burst 당 connect ≤1회(nested bound,
  per-attempt backoff 미적용 — 5×120s 누적 부재).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import ante.main as main_module
from ante.account.models import TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.broker.exceptions import AuthenticationError, TokenRateLimitError
from ante.broker.kis import DEFAULT_MAX_RETRIES_AUTH


def _account(account_id: str = "live-1") -> Any:
    return SimpleNamespace(
        account_id=account_id,
        broker_type="kis-domestic",
        trading_mode=TradingMode.LIVE,
        exchange="KRX",
        credentials={},
        broker_config={},
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """asyncio.sleep 을 patch 해 실제 대기 없이 호출량을 관측 (T4 nested bound)."""
    slept: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(main_module.asyncio, "sleep", _fake_sleep)
    return slept


# ── T4 (c): startup wrapper bounded retry ──────────────────


class TestStartupAuthRetryWrapper:
    async def test_egw00133_absorbed_then_success(
        self, _no_real_sleep: list[float]
    ) -> None:
        """EGW00133 흡수 후 성공 — bounded retry 내 회복."""
        broker = AsyncMock()
        state = {"fails": 1}

        async def _connect() -> None:
            if state["fails"] > 0:
                state["fails"] -= 1
                raise TokenRateLimitError("x", error_code="EGW00133")

        broker.connect = AsyncMock(side_effect=_connect)

        await main_module._connect_broker_with_auth_retry(broker)

        assert broker.connect.await_count == 2  # 1 실패 + 1 성공
        # backoff sleep 1회(흡수).
        assert len(_no_real_sleep) == 1

    async def test_egw00133_exhausts_max_retries_then_raises(
        self, _no_real_sleep: list[float]
    ) -> None:
        """persistent EGW00133 → DEFAULT_MAX_RETRIES_AUTH 소진 후 전파."""
        broker = AsyncMock()
        broker.connect = AsyncMock(
            side_effect=TokenRateLimitError("x", error_code="EGW00133")
        )

        with pytest.raises(TokenRateLimitError):
            await main_module._connect_broker_with_auth_retry(broker)

        # 최초 1 + 재시도 DEFAULT_MAX_RETRIES_AUTH 회.
        assert broker.connect.await_count == DEFAULT_MAX_RETRIES_AUTH + 1
        # backoff sleep = 재시도 횟수만큼(소진 직전까지). startup 한 곳만(곱셈 없음).
        assert len(_no_real_sleep) == DEFAULT_MAX_RETRIES_AUTH

    async def test_non_egw00133_propagates_immediately(
        self, _no_real_sleep: list[float]
    ) -> None:
        """비-EGW00133 예외는 흡수 retry 없이 즉시 전파(기존 동작 유지)."""
        broker = AsyncMock()
        broker.connect = AsyncMock(
            side_effect=AuthenticationError("bad key", error_code="EGW00121")
        )

        with pytest.raises(AuthenticationError):
            await main_module._connect_broker_with_auth_retry(broker)

        assert broker.connect.await_count == 1
        assert _no_real_sleep == []  # backoff 없음


# ── T6: startup connect 루프 reason 보존 ───────────────────


class TestConnectFailureReason:
    def test_reason_from_error_code(self) -> None:
        """error_code 보유 예외 → reason=error_code (구조적, 문자열 grep 아님)."""
        exc = TokenRateLimitError("x", error_code="EGW00133")
        assert main_module._connect_failure_reason(exc, "connect_failed") == "EGW00133"

    def test_reason_default_when_no_code(self) -> None:
        """error_code 없으면 default reason."""
        exc = RuntimeError("network down")
        assert (
            main_module._connect_failure_reason(exc, "connect_failed")
            == "connect_failed"
        )

    def test_reason_default_when_empty_code(self) -> None:
        """error_code 빈 문자열이면 default reason."""
        exc = AuthenticationError("generic", error_code="")
        assert (
            main_module._connect_failure_reason(exc, "reconnect_failed")
            == "reconnect_failed"
        )


# ── T4 (b): self-healing recover EGW00133 → re-raise + reason ──


def _self_healing_services(broker: Any) -> Any:
    s = main_module.Services()
    s.runtime_readiness = RuntimeReadinessRegistry()
    s.order_tracker = None
    s.fill_applier = None
    s.trade_service = None
    s.eventbus = AsyncMock()
    s.instrument_service = object()
    s.bot_manager = object()
    s.treasury_manager = None
    s.config = SimpleNamespace(get=lambda key, default=None: default)

    account_service = AsyncMock()
    account_service.get_broker = AsyncMock(return_value=broker)
    s.account_service = account_service  # type: ignore[assignment]
    return s


class TestSelfHealingEGW00133:
    async def test_recover_reraises_and_preserves_reason(self) -> None:
        """recover_account: EGW00133 → reason 보존 + TokenRateLimitError re-raise."""
        broker = AsyncMock()
        broker.connect = AsyncMock(
            side_effect=TokenRateLimitError("x", error_code="EGW00133")
        )
        s = _self_healing_services(broker)
        account = _account()
        s.runtime_readiness.mark_not_ready(
            "live-1", ReadinessFlag.BROKER, "connect_failed"
        )

        with pytest.raises(TokenRateLimitError):
            await main_module._self_healing_recover_account(s, account)

        # T6: reason 에 EGW00133 보존.
        assert (
            s.runtime_readiness.get_reason("live-1", ReadinessFlag.BROKER) == "EGW00133"
        )

    async def test_recover_other_transient_returns_false_no_raise(self) -> None:
        """다른 transient(비-EGW00133) → False 반환(re-raise 없음, 기존 backoff)."""
        broker = AsyncMock()
        broker.connect = AsyncMock(side_effect=RuntimeError("conn reset"))
        s = _self_healing_services(broker)
        account = _account()
        s.runtime_readiness.mark_not_ready(
            "live-1", ReadinessFlag.BROKER, "connect_failed"
        )

        result = await main_module._self_healing_recover_account(s, account)
        assert result is False
        assert (
            s.runtime_readiness.get_reason("live-1", ReadinessFlag.BROKER)
            == "reconnect_failed"
        )


# ── T4 (b): self-healing burst loop nested bound ───────────


class TestSelfHealingBurstBound:
    async def test_persistent_egw00133_one_connect_per_burst(
        self, _no_real_sleep: list[float]
    ) -> None:
        """persistent EGW00133: burst 당 connect 시도 ≤1회 (nested bound, 5×120s 부재).

        per-attempt backoff(min(backoff_base*2^attempt, max))가 누적되지 않고,
        EGW00133 break 로 다음 interval(60s)에만 위임됨을 connect 호출량으로 잠근다.
        """
        connect_calls = {"count": 0}

        broker = AsyncMock()

        async def _connect() -> None:
            connect_calls["count"] += 1
            raise TokenRateLimitError("x", error_code="EGW00133")

        broker.connect = AsyncMock(side_effect=_connect)

        s = main_module.Services()
        s.runtime_readiness = RuntimeReadinessRegistry()
        s.order_tracker = None
        s.fill_applier = None
        s.trade_service = None
        s.eventbus = AsyncMock()
        s.instrument_service = object()
        s.bot_manager = object()
        s.treasury_manager = None
        # max_per_burst=5 — EGW00133 break 가 없으면 burst 당 connect 5회가 된다.
        s.config = SimpleNamespace(
            get=lambda key, default=None: {
                "readiness.self_healing_interval_seconds": 60,
                "readiness.self_healing_max_attempts_per_burst": 5,
                "readiness.self_healing_backoff_base_seconds": 5,
                "readiness.self_healing_backoff_max_seconds": 60,
            }.get(key, default)
        )

        account_service = AsyncMock()
        account_service.get_broker = AsyncMock(return_value=broker)
        s.account_service = account_service  # type: ignore[assignment]

        s.runtime_readiness.mark_not_ready(
            "live-1", ReadinessFlag.BROKER, "connect_failed"
        )
        account = _account()

        task = asyncio.create_task(
            main_module._readiness_self_healing_loop(s, [account])
        )
        # interval sleep(60s)이 2회 관측될 때까지 진행 → 2 burst 경과.
        try:
            for _ in range(100):
                interval_sleeps = [d for d in _no_real_sleep if d == 60]
                if len(interval_sleeps) >= 2:
                    break
                await asyncio.sleep(0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # burst break 검증: 경과한 burst 수만큼만 connect(burst 당 ≤1회).
        # interval sleep 2회 관측 시점 → 2~3 burst 진행, connect 도 그 범위.
        interval_count = len([d for d in _no_real_sleep if d == 60])
        assert connect_calls["count"] <= interval_count + 1, (
            f"burst 당 connect ≤1 위반: connect={connect_calls['count']}, "
            f"interval={interval_count}"
        )
        # per-attempt backoff(min(5*2^a, 60) = 5/10/20/40 초)가 누적되지 않았다
        # (EGW00133 break — 0 은 테스트 폴링 sleep, 60 은 burst interval 이므로 제외).
        per_attempt_values = {5, 10, 20, 40}
        leaked = [d for d in _no_real_sleep if d in per_attempt_values]
        assert leaked == [], (
            f"EGW00133 burst 에서 per-attempt backoff 누적 금지 위반: {leaked}"
        )
