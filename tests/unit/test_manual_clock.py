"""tests/conftest.py의 ManualClock과 manual_clock 픽스처 (#2768)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ante.core import clock

_KST = timezone(timedelta(hours=9))
_AT = datetime(2026, 3, 4, 14, 59, 0, tzinfo=_KST)


def test_manual_clock_is_current_clock(manual_clock) -> None:
    assert clock.current_clock() is manual_clock


def test_default_time_is_fixed(manual_clock) -> None:
    first = clock.now(UTC)
    second = clock.now(UTC)
    assert first == second
    assert first.tzinfo is UTC


@pytest.mark.parametrize("manual_clock", [_AT], indirect=True)
def test_now_converts_fixed_time_to_tz(manual_clock) -> None:
    assert clock.now(_KST) == _AT
    assert clock.now(_KST).utcoffset() == timedelta(hours=9)
    assert clock.now(UTC) == _AT.astimezone(UTC)
    assert clock.now(UTC).tzinfo is UTC


@pytest.mark.parametrize("manual_clock", [_AT], indirect=True)
def test_now_none_is_naive_local_time(manual_clock) -> None:
    naive = clock.now(None)
    assert naive.tzinfo is None
    assert naive == _AT.astimezone().replace(tzinfo=None)


def test_monotonic_is_fixed_until_advance(manual_clock) -> None:
    start = clock.monotonic()
    assert clock.monotonic() == start
    manual_clock.advance(1.5)
    assert clock.monotonic() == start + 1.5


@pytest.mark.parametrize("manual_clock", [_AT], indirect=True)
def test_advance_moves_wall_and_monotonic(manual_clock) -> None:
    manual_clock.advance(61)
    assert clock.now(_KST) == datetime(2026, 3, 4, 15, 0, 1, tzinfo=_KST)


def test_advance_rejects_negative(manual_clock) -> None:
    with pytest.raises(ValueError):
        manual_clock.advance(-1)


def test_naive_start_is_rejected(manual_clock) -> None:
    with pytest.raises(ValueError):
        type(manual_clock)(datetime(2026, 1, 1))


def test_system_clock_is_back_after_fixture() -> None:
    assert type(clock.current_clock()) is clock.SystemClock
