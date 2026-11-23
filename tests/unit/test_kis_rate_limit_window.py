"""KIS 어댑터 요청 창(분당 한도)과 토큰 쿨다운의 시계 단위 테스트 (#2784).

- 요청 창은 깬 뒤의 단조 시각을 기록하고, 판정·대기·기록을 잠금 하나로 묶는다.
- 쿨다운은 단조 마감으로 재고, 예외의 ``cooldown_until``은 raise 시점의 잔여로 만든다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest

import ante.broker.kis as kis_module
from ante.broker import KISAdapter
from ante.broker.kis import (
    TOKEN_RATE_LIMIT_COOLDOWN_SECONDS,
    _record_token_cooldown,
    _token_cooldown_until,
)
from ante.core import clock

_WINDOW = 60.0
_LIMIT = 2
_WALL_AT = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)


class _SplitClock:
    """벽시계와 단조 값을 따로 움직일 수 있는 시계 대역."""

    def __init__(self) -> None:
        self._at = _WALL_AT
        self._monotonic = 1000.0

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self._at.astimezone().replace(tzinfo=None)
        return self._at.astimezone(tz)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        assert seconds >= 0
        self._at += timedelta(seconds=seconds)
        self._monotonic += seconds

    def shift_wall(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)


@pytest.fixture
def split_clock() -> Iterator[_SplitClock]:
    with clock.use_clock(_SplitClock()) as installed:
        yield installed


@pytest.fixture
def yielding_sleep(
    split_clock: _SplitClock, monkeypatch: pytest.MonkeyPatch
) -> list[float]:
    """시계를 잔 만큼 나아가게 한 뒤 실제로 한 번 양보하는 가짜 sleep."""
    original_sleep = asyncio.sleep
    slept: list[float] = []

    async def _fake_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        slept.append(delay)
        split_clock.advance(delay)
        await original_sleep(0)

    monkeypatch.setattr(kis_module.asyncio, "sleep", _fake_sleep)
    return slept


def _make_adapter() -> KISAdapter:
    adapter = KISAdapter(
        {
            "app_key": "rate_key",
            "app_secret": "secret",
            "account_no": "1111111101",
            "is_paper": True,
        }
    )
    adapter._rate_limit_per_minute = _LIMIT
    return adapter


async def _send(adapter: KISAdapter) -> float:
    await adapter._rate_limit_wait()
    return clock.monotonic()


def _advance_to(split_clock: _SplitClock, base: float, offset: float) -> None:
    target = base + offset
    if split_clock.monotonic() < target:
        split_clock.advance(target - split_clock.monotonic())


def _max_in_any_window(sends: list[float]) -> int:
    return max(sum(1 for s in sends if t - _WINDOW < s <= t) for t in sends)


class TestRequestWindow:
    async def test_sequential_sends_never_exceed_limit_in_any_window(
        self, split_clock: _SplitClock, yielding_sleep: list[float]
    ) -> None:
        """잠들기 전 시각을 기록하면 60·61·90초 송신이 한 창에 셋이 된다."""
        adapter = _make_adapter()
        base = split_clock.monotonic()
        sends: list[float] = []
        for offset in (0.0, 1.0, 30.0, 60.5, 61.0):
            _advance_to(split_clock, base, offset)
            sends.append(await _send(adapter))

        assert _max_in_any_window(sends) <= _LIMIT
        assert [s - base for s in sends] == [0.0, 1.0, 60.0, 61.0, 120.0]

    async def test_concurrent_sends_on_full_window_keep_limit(
        self, split_clock: _SplitClock, yielding_sleep: list[float]
    ) -> None:
        """창이 찬 상태에서 동시에 든 셋은 든 순서대로 줄을 서서 한도를 지킨다."""
        adapter = _make_adapter()
        base = split_clock.monotonic()
        sends = [await _send(adapter)]
        _advance_to(split_clock, base, 0.5)
        sends.append(await _send(adapter))
        _advance_to(split_clock, base, 1.0)

        sends.extend(await asyncio.gather(*(_send(adapter) for _ in range(3))))

        assert _max_in_any_window(sends) <= _LIMIT
        assert sends == sorted(sends), "먼저 든 요청이 먼저 나가야 한다"
        assert [s - base for s in sends] == [0.0, 0.5, 60.0, 60.5, 120.0]
        assert yielding_sleep == [59.0, 0.5, 59.5]

    async def test_early_wakeup_rechecks_window_before_sending(
        self, split_clock: _SplitClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """요청보다 일찍 깨면 창을 다시 보고 남은 만큼 더 잔다."""
        original_sleep = asyncio.sleep
        slept: list[float] = []

        async def _early_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
            slept.append(delay)
            split_clock.advance(delay - 1.0 if delay > 1.0 else delay)
            await original_sleep(0)

        monkeypatch.setattr(kis_module.asyncio, "sleep", _early_sleep)
        adapter = _make_adapter()
        base = split_clock.monotonic()
        sends = [await _send(adapter)]
        _advance_to(split_clock, base, 1.0)
        sends.append(await _send(adapter))
        _advance_to(split_clock, base, 2.0)

        sends.append(await _send(adapter))

        assert _max_in_any_window(sends) <= _LIMIT
        assert sends[-1] - base == _WINDOW
        assert slept == [58.0, 1.0]

    async def test_wall_clock_going_back_does_not_stretch_wait(
        self, split_clock: _SplitClock, yielding_sleep: list[float]
    ) -> None:
        """벽시계만 한 시간 뒤로 가도 대기는 창의 잔여를 넘지 않는다."""
        adapter = _make_adapter()
        base = split_clock.monotonic()
        await _send(adapter)
        _advance_to(split_clock, base, 1.0)
        await _send(adapter)
        _advance_to(split_clock, base, 10.0)
        split_clock.shift_wall(-3600.0)

        sent = await _send(adapter)

        assert yielding_sleep == [50.0]
        assert sent - base == 60.0

    async def test_wall_clock_going_forward_does_not_empty_window(
        self, split_clock: _SplitClock, yielding_sleep: list[float]
    ) -> None:
        """벽시계만 앞으로 가도 창은 비지 않고 한도를 지킨다."""
        adapter = _make_adapter()
        base = split_clock.monotonic()
        sends = [await _send(adapter)]
        _advance_to(split_clock, base, 1.0)
        sends.append(await _send(adapter))
        _advance_to(split_clock, base, 10.0)
        split_clock.shift_wall(3600.0)

        sends.append(await _send(adapter))

        assert _max_in_any_window(sends) <= _LIMIT
        assert sends[-1] - base == 60.0


class TestTokenCooldownMonotonic:
    def test_wall_forward_does_not_release_cooldown_early(
        self, split_clock: _SplitClock
    ) -> None:
        """벽시계가 앞으로 가도 쿨다운은 단조 60초 동안 이어진다."""
        _record_token_cooldown("cool_key")
        split_clock.advance(10.0)
        split_clock.shift_wall(3600.0)

        until = _token_cooldown_until("cool_key")

        assert until is not None
        assert until - clock.now(UTC) == timedelta(seconds=50.0)
        split_clock.advance(TOKEN_RATE_LIMIT_COOLDOWN_SECONDS - 10.0)
        assert _token_cooldown_until("cool_key") is None

    def test_wall_back_does_not_extend_cooldown(self, split_clock: _SplitClock) -> None:
        """벽시계가 뒤로 가도 쿨다운은 단조 60초에 풀린다."""
        _record_token_cooldown("cool_key")
        split_clock.shift_wall(-3600.0)
        split_clock.advance(TOKEN_RATE_LIMIT_COOLDOWN_SECONDS - 0.5)

        until = _token_cooldown_until("cool_key")

        assert until is not None
        assert until - clock.now(UTC) == timedelta(seconds=0.5)
        split_clock.advance(0.5)
        assert _token_cooldown_until("cool_key") is None
