"""Canonical exchange vocabulary — 코드 레벨 SSOT.

이 모듈은 Ante 전역에서 `exchange`가 의미하는 canonical vocabulary의
**코드 레벨 단일 출처(SSOT)** 다. 계약 본문은 스펙에 있으며 본 모듈은
그 값 집합을 코드에서 단일화한다:

    docs/specs/core/core.md ``## Canonical Exchange Vocabulary``
    docs/decisions/D-016-canonical-exchange-vocabulary.md

범위 불변식 (#1576 narrow-scope):
    - 본 모듈은 **축 A — exchange-vocabulary 유효성** (canonical 5종 + `*`
      정책) 의 값 집합·검증 헬퍼만 정의한다.
    - surface별 enforcement·에러 계층·preset/broker 가용성(축 B)·신규
      표면 validation 추가는 본 모듈의 범위가 아니다 (#1577/#1578).
    - 대소문자 정규화·별칭(alias)·사용자 정의 exchange set은 1.0 비목표다
      (core.md ``### Canonical set``). 입력은 아래 canonical 리터럴과
      **정확히 일치**해야 한다 — 본 모듈의 헬퍼는 어떤 변환도 하지 않는다.
"""

from __future__ import annotations

# canonical exchange — 대문자 고정 5종 (core.md ``### Canonical set``).
# 신규 입력 검증 vocabulary 전체이며 불변이다.
CANONICAL_EXCHANGES: frozenset[str] = frozenset(
    {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST"}
)

# `*` 는 실제 exchange가 아니라 ``StrategyMeta.exchange`` 전용 wildcard다
# (core.md ``### Wildcard 정책``). 다른 어떤 표면에서도 허용되지 않는다.
STRATEGY_WILDCARD: str = "*"

# strategy 표면(``StrategyMeta.exchange``)이 허용하는 집합:
# canonical 5종 ∪ {`*`}. account/instrument/data 표면은 wildcard를
# 제외한 ``CANONICAL_EXCHANGES`` 만 허용한다.
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
    ``is_strategy_allowed`` 로 별도 검증해야 한다 (Codex Plan Review q5).
    """
    return value
