from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now(self, tz: tzinfo | None) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self, tz: tzinfo | None) -> datetime:
        return datetime.now(tz)

    def monotonic(self) -> float:
        return time.monotonic()


_current: Clock = SystemClock()


def current_clock() -> Clock:
    return _current


def set_clock(clock: Clock) -> Clock:
    global _current
    previous = _current
    _current = clock
    return previous


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    previous = set_clock(clock)
    try:
        yield clock
    finally:
        set_clock(previous)


def now(tz: tzinfo | None) -> datetime:
    return _current.now(tz)


def monotonic() -> float:
    return _current.monotonic()
