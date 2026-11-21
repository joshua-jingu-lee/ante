"""Canonical exchange vocabulary — 코드 레벨 SSOT."""

from __future__ import annotations

CANONICAL_EXCHANGES: frozenset[str] = frozenset(
    {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST"}
)

STRATEGY_WILDCARD: str = "*"

STRATEGY_EXCHANGES: frozenset[str] = CANONICAL_EXCHANGES | {STRATEGY_WILDCARD}


def is_canonical(value: str) -> bool:
    """``value`` 가 canonical exchange 5종 중 하나인지 (exact-literal).

    `*` 는 canonical exchange가 아니므로 ``False`` 다. 대소문자/별칭
    정규화는 수행하지 않는다 — 입력은 canonical 리터럴과 정확히
    일치해야 한다 (core.md ``### Canonical set``).
    """
    return value in CANONICAL_EXCHANGES


def is_strategy_allowed(value: str) -> bool:
    """``value`` 가 strategy 표면(canonical 5종 ∪ {`*`})에서 허용되는지.

    ``StrategyMeta.exchange`` 전용 wildcard `*` 를 포함한다. 대소문자/
    별칭 정규화는 수행하지 않는다 (exact-literal).
    """
    return value in STRATEGY_EXCHANGES


def normalize_exchange(value: str) -> str:
    """exact-literal passthrough — **변환하지 않는다**.

    core.md ``### Canonical set`` 에 따라 대소문자 정규화·별칭 매핑은
    1.0 비목표다. 이 헬퍼는 어떤 변환도 수행하지 않고 입력을 그대로
    돌려준다. 호출자는 반환값을 ``is_canonical`` /
    ``is_strategy_allowed`` 로 별도 검증해야 한다.
    """
    return value
