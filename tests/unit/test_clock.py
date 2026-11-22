"""ante.core.clock — 시각 판독의 단일 통로 (#2768)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from ante.core import clock
from ante.core.clock import Clock, SystemClock, monotonic, now, set_clock, use_clock

_KST = timezone(timedelta(hours=9))
_FIXED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class _FixedClock:
    def __init__(self, at: datetime, mono: float) -> None:
        self.at = at
        self.mono = mono

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self.at.replace(tzinfo=None)
        return self.at.astimezone(tz)

    def monotonic(self) -> float:
        return self.mono


def test_system_clock_now_utc_is_aware_and_current() -> None:
    before = datetime.now(UTC)
    value = SystemClock().now(UTC)
    after = datetime.now(UTC)
    assert value.tzinfo is UTC
    assert before <= value <= after


def test_system_clock_now_respects_tz() -> None:
    value = SystemClock().now(_KST)
    assert value.utcoffset() == timedelta(hours=9)


def test_system_clock_now_none_is_naive() -> None:
    assert SystemClock().now(None).tzinfo is None


def test_system_clock_monotonic_does_not_decrease() -> None:
    system = SystemClock()
    values = [system.monotonic() for _ in range(100)]
    assert values == sorted(values)


def test_system_clock_satisfies_protocol() -> None:
    system: Clock = SystemClock()
    assert isinstance(system.monotonic(), float)


def test_default_clock_is_system_clock() -> None:
    assert isinstance(clock.current_clock(), SystemClock)


def test_set_clock_returns_previous_and_module_functions_delegate() -> None:
    fixed = _FixedClock(_FIXED, 42.0)
    previous = set_clock(fixed)
    try:
        assert isinstance(previous, SystemClock)
        assert clock.current_clock() is fixed
        assert now(UTC) == _FIXED
        assert now(_KST) == _FIXED.astimezone(_KST)
        assert now(None) == _FIXED.replace(tzinfo=None)
        assert monotonic() == 42.0
    finally:
        assert set_clock(previous) is fixed
    assert clock.current_clock() is previous


def test_imported_function_sees_replacement_at_call_time() -> None:
    from ante.core.clock import now as imported_now

    with use_clock(_FixedClock(_FIXED, 0.0)):
        assert imported_now(UTC) == _FIXED


def test_use_clock_restores_after_block() -> None:
    previous = clock.current_clock()
    fixed = _FixedClock(_FIXED, 1.0)
    with use_clock(fixed) as entered:
        assert entered is fixed
        assert clock.current_clock() is fixed
    assert clock.current_clock() is previous


def test_use_clock_restores_on_exception() -> None:
    previous = clock.current_clock()
    with pytest.raises(RuntimeError), use_clock(_FixedClock(_FIXED, 1.0)):
        raise RuntimeError("boom")
    assert clock.current_clock() is previous


def test_use_clock_nests() -> None:
    previous = clock.current_clock()
    outer = _FixedClock(_FIXED, 1.0)
    inner = _FixedClock(_FIXED + timedelta(hours=1), 2.0)
    with use_clock(outer):
        with use_clock(inner):
            assert monotonic() == 2.0
        assert clock.current_clock() is outer
        assert monotonic() == 1.0
    assert clock.current_clock() is previous
