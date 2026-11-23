r"""Canonical symbol/timeframe vocabulary — 코드 레벨 SSOT."""

from __future__ import annotations

import re

CANONICAL_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

TIMEFRAME_SET: frozenset[str] = frozenset(CANONICAL_TIMEFRAMES)

_KRX_SYMBOL_REGEX: re.Pattern[str] = re.compile(r"\A[0-9]{6}\Z")


def is_valid_timeframe(value: str) -> bool:
    """``value`` 가 canonical OHLCV bar timeframe 5종 중 하나인지.

    exact-literal 멤버십만 본다. alias(`1min`/`D`/`daily`/`1D`)·
    대소문자 정규화는 수행하지 않는다 — 입력은 canonical 리터럴과
    정확히 일치해야 한다 (core.md ``### Canonical timeframe set``).
    """
    return value in TIMEFRAME_SET


def is_krx_symbol(value: str) -> bool:
    r"""``value`` 가 신규 입력 KRX symbol shape(`^[0-9]{6}$`)인지."""
    return isinstance(value, str) and _KRX_SYMBOL_REGEX.fullmatch(value) is not None
