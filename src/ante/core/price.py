"""가격 값의 공용 판정 — 의존 없는 순수 술어."""

from __future__ import annotations

import math
from typing import TypeGuard


def is_valid_price(value: object) -> TypeGuard[int | float]:
    """``value`` 가 불리언이 아닌 유한한 수이고 0보다 크면 참.

    ``float`` 로 바꿀 수 없을 만큼 큰 정수는 무한대로 보아 거짓이다.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        price = float(value)
    except OverflowError:
        return False
    return math.isfinite(price) and price > 0
