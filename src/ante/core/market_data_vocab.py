r"""Canonical symbol/timeframe vocabulary — 코드 레벨 SSOT.

이 모듈은 Ante 전역에서 OHLCV bar `timeframe`과 신규 입력 KRX `symbol`이
의미하는 canonical vocabulary의 **코드 레벨 단일 출처(SSOT)** 다. 계약
본문은 스펙에 있으며 본 모듈은 그 값 집합·검증 헬퍼를 코드에서 단일화한다:

    docs/specs/core/core.md ``## Canonical Symbol/Timeframe Vocabulary``
    docs/decisions/D-017-canonical-symbol-timeframe-vocabulary.md

범위 불변식 (#1613 narrow-scope):
    - 본 모듈은 **축 A — OHLCV bar timeframe canonical set** (고정 5종·
      고정 순서) 과 **축 E — 신규 입력 KRX symbol shape** (`^[0-9]{6}$`,
      exchange == KRX 신규 입력 한정) 의 값 집합·검증 헬퍼만 정의한다.
    - surface별 enforcement·에러 계층·신규 표면 validation 추가는 본
      모듈의 범위가 아니다 (#1603/#1604/#1605/#1606/#1611/#1614,
      #1594 잔여 symbol filter).
    - alias(예: `1min`/`D`/`daily`/`1D`)·대소문자 정규화·사용자 정의
      timeframe set은 1.0 비목표다 (core.md ``### Canonical timeframe
      set``). 입력은 아래 canonical 리터럴과 **정확히 일치**해야 한다 —
      본 모듈의 헬퍼는 어떤 변환도(no-alias·no-normalization) 하지 않는다.
    - 축 E 분리: 신규 입력 strict ASCII 검증(본 모듈)과 legacy parquet
      path migration 판별(`src/ante/data/store.py` `\d` Unicode 보존)은
      별개 축이다 (core.md ``### Legacy out-of-vocabulary 호환 정책``).
      legacy 판별 regex는 본 SSOT로 위임·대체·강화되지 않는다.
"""

from __future__ import annotations

import re

# canonical OHLCV bar timeframe — 고정 집합·고정 순서 5종
# (core.md ``### Canonical timeframe set``). 표기 순서
# (`1m → 5m → 15m → 1h → 1d`)는 순서 의존 소비자(예:
# `src/ante/cli/commands/data.py`의 iteration)를 위해 계약상 고정한다.
# 따라서 순서가 의미를 갖는 tuple로 둔다 — 신규 입력 검증 vocabulary
# 전체이며 불변이다.
CANONICAL_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

# 멤버십(in) 검증용 집합. 값은 ``CANONICAL_TIMEFRAMES`` 와 동일하며
# 순서 비의존 소비자(예: `retention.py`)가 위임한다.
TIMEFRAME_SET: frozenset[str] = frozenset(CANONICAL_TIMEFRAMES)

# 신규 입력 KRX symbol shape: 6자리 ASCII digit (core.md
# ``### KRX symbol shape`` — exchange == KRX 신규 입력 경계 한정).
# ``\A...\Z`` 앵커 + ``fullmatch`` 는 trailing ``\n`` 까지 거부한다
# (``re.match(r"^[0-9]{6}$", "123456\n")`` 는 True이므로 ``^...$``+
# ``match`` 로는 #1299 fail-closed 회귀. fullmatch 엄격도 유지).
_KRX_SYMBOL_REGEX: re.Pattern[str] = re.compile(r"\A[0-9]{6}\Z")


def is_valid_timeframe(value: str) -> bool:
    """``value`` 가 canonical OHLCV bar timeframe 5종 중 하나인지.

    exact-literal 멤버십만 본다. alias(`1min`/`D`/`daily`/`1D`)·
    대소문자 정규화는 수행하지 않는다 — 입력은 canonical 리터럴과
    정확히 일치해야 한다 (core.md ``### Canonical timeframe set``).
    """
    return value in TIMEFRAME_SET


def is_krx_symbol(value: str) -> bool:
    r"""``value`` 가 신규 입력 KRX symbol shape(`^[0-9]{6}$`)인지.

    ``fullmatch`` 로 검사하여 leading/trailing whitespace·trailing
    ``\n`` 을 모두 거부한다 (core.md ``### KRX symbol shape``,
    #1299 fail-closed 엄격도 유지). 비문자열 입력은 ``re`` 가
    ``TypeError`` 를 던지므로 ``isinstance`` 로 선검사 후 ``False`` 로
    잠근다. 이 헬퍼는 어떤 정규화도(no-normalization) 하지 않으며
    Unicode digit(예: `１２３４５６`)은 ASCII `[0-9]` 가 아니므로
    거부된다. resolved exchange == KRX인 신규 입력 경계에서만 적용해야
    하며(비-KRX exchange symbol format은 1.0 비목표), exchange 귀속
    판정은 호출자 책임이다.
    """
    return isinstance(value, str) and _KRX_SYMBOL_REGEX.fullmatch(value) is not None
