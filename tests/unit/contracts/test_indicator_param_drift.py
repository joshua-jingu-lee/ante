"""지표 파라미터 키 docs↔런타임 drift 계약 테스트 (#2404).

스펙(`docs/specs/strategy/03-06-indicator-calculator.md`)과 공개 가이드
(`guide/strategy.md`)가 안내하는 지표 파라미터 키가 런타임
``INDICATOR_REGISTRY`` 및 ``IndicatorCalculator.compute()`` 계약과 어긋나지
않도록 강제한다.

배경: pandas-ta 도입 이전 TA-Lib 규약 키(``timeperiod`` / ``nbdev`` /
``fastk`` / ``slowk`` / ``slowd``)가 docs에 남아 있었고, 그대로 전달하면
pandas-ta가 ``**kwargs``로 흡수해 조용히 무시(silent-drop)했다. 본 테스트는
세 축을 검증한다:

(a) docs↔키 계약 — spec 표·guide 표·guide 예제에서 추출한 파라미터 키에
    블랙리스트(legacy) 키가 등장하지 않고, 각 키가 해당 지표의 정식 레지스트리
    키임을 단언.
(b) 레지스트리 honored 행위 검증 — params를 가진 각 지표의 각 레지스트리
    키를 비기본값으로 전달했을 때 결과가 기본 출력과 **달라짐**을 단언
    (silent-drop 직접 검출; bbands ``std`` 류 회귀 차단).
(c) 가드 동작 — ``compute(..., timeperiod=...)`` 등 블랙리스트 키 전달 시
    정정 키 힌트를 담은 ``ValueError``가 발생함을 단언.

기존 ``helpers.py``의 ``_DOCS_ROW_RE``는 CLI command 행(``| `ante ...```)
전용이라 지표 표 파싱에 재사용할 수 없어 신규 파서를 둔다.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from ante.strategy.indicators import (
    _LEGACY_PARAM_KEYS,
    INDICATOR_REGISTRY,
    IndicatorCalculator,
)

# ── repo root 고정 ───────────────────────────────────────────────────────────
# tests/unit/contracts/이 파일 → 3단계 위가 repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC_PATH = (
    _REPO_ROOT / "docs" / "specs" / "strategy" / "03-06-indicator-calculator.md"
)
_GUIDE_PATH = _REPO_ROOT / "guide" / "strategy.md"


# ── 파서 ─────────────────────────────────────────────────────────────────────

# `length=20` / `lower_std=2.0` 같은 key=value 토큰에서 key만 추출.
_KV_KEY_RE = re.compile(r"([A-Za-z_]\w*)\s*=")
# `{"length": 14}` 같은 dict 리터럴에서 문자열 키 추출 (get_indicator 예제).
_DICT_KEY_RE = re.compile(r'["\']([A-Za-z_]\w*)["\']\s*:')
# 백틱으로 감싼 식별자 (guide 표의 `length`, `fast` 등).
_BACKTICK_KEY_RE = re.compile(r"`([A-Za-z_]\w*)`")


def _spec_table_param_keys() -> set[str]:
    """spec 03-06 '지원 지표' 표의 `기본 파라미터` 열에서 키를 추출.

    표 행(`| 지표 | 함수 | 입력 | 기본 파라미터 |`)만 파싱한다. negative-mention
    산문 줄(예: 'TA-Lib의 timeperiod ... 가 아니다')은 표 행이 아니므로 자동
    제외된다.
    """
    text = _SPEC_PATH.read_text(encoding="utf-8")
    keys: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # 4열 표 (지표 | 함수 | 입력 | 기본 파라미터)만 대상.
        if len(cells) != 4:
            continue
        last = cells[-1]
        # 헤더/구분선/'—'(파라미터 없음) 행 스킵.
        if "=" not in last:
            continue
        keys.update(_KV_KEY_RE.findall(last))
    return keys


def _guide_table_param_keys() -> set[str]:
    """guide '지원 지표(15종)' 표의 `주요 파라미터` 열 백틱 키를 추출.

    `| 지표 | 이름 | 주요 파라미터 |` 헤더로 시작하는 표 블록의 데이터 행만
    파싱한다. guide에는 동일한 3열 구조의 다른 표(에이전트 메시지 타입 등)가
    있으므로, 헤더 텍스트로 대상 표를 특정해 오탐을 막는다.
    """
    text = _GUIDE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    keys: set[str] = set()
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 3:
            in_table = False
            continue
        # 지표 표 헤더 행 식별 → 블록 시작.
        if cells == ["지표", "이름", "주요 파라미터"]:
            in_table = True
            continue
        if not in_table:
            continue
        # 구분선 행(---) 스킵.
        if set(cells[-1]) <= {"-", ":", " "}:
            continue
        keys.update(_BACKTICK_KEY_RE.findall(cells[-1]))
    return keys


def _guide_example_param_keys() -> set[str]:
    """guide 코드 예제의 ``get_indicator(..., {"key": val})`` dict 키를 추출."""
    text = _GUIDE_PATH.read_text(encoding="utf-8")
    keys: set[str] = set()
    for m in re.finditer(r"get_indicator\([^)]*\{([^}]*)\}", text):
        keys.update(_DICT_KEY_RE.findall(m.group(1)))
    return keys


# 레지스트리에 등록된 모든 정식 파라미터 키(전 지표 합집합).
_REGISTRY_PARAM_KEYS: set[str] = {
    key for spec in INDICATOR_REGISTRY.values() for key in spec["params"]
}


# ── (a) docs↔키 계약 ─────────────────────────────────────────────────────────


def test_spec_table_keys_have_no_legacy_keys() -> None:
    """spec 표의 파라미터 키에 블랙리스트(legacy) 키가 없다."""
    keys = _spec_table_param_keys()
    assert keys, "spec 표에서 파라미터 키를 하나도 추출하지 못함 (파서 회귀)"
    leaked = keys & set(_LEGACY_PARAM_KEYS)
    assert not leaked, f"spec 03-06 표가 legacy 키를 안내: {sorted(leaked)}"


def test_spec_table_keys_are_registry_keys() -> None:
    """spec 표의 각 파라미터 키가 레지스트리 정식 키다."""
    keys = _spec_table_param_keys()
    unknown = keys - _REGISTRY_PARAM_KEYS
    assert not unknown, f"spec 03-06 표 키가 레지스트리에 없음: {sorted(unknown)}"


def test_guide_table_keys_have_no_legacy_keys() -> None:
    """guide 표의 파라미터 키에 블랙리스트 키가 없다."""
    keys = _guide_table_param_keys()
    assert keys, "guide 표에서 파라미터 키를 하나도 추출하지 못함 (파서 회귀)"
    leaked = keys & set(_LEGACY_PARAM_KEYS)
    assert not leaked, f"guide/strategy.md 표가 legacy 키를 안내: {sorted(leaked)}"


def test_guide_table_keys_are_registry_keys() -> None:
    """guide 표의 각 파라미터 키가 레지스트리 정식 키다."""
    keys = _guide_table_param_keys()
    unknown = keys - _REGISTRY_PARAM_KEYS
    assert not unknown, f"guide 표 키가 레지스트리에 없음: {sorted(unknown)}"


def test_guide_examples_have_no_legacy_keys() -> None:
    """guide 코드 예제의 get_indicator dict 키에 블랙리스트 키가 없다."""
    keys = _guide_example_param_keys()
    assert keys, "guide 예제에서 get_indicator 파라미터 키를 추출하지 못함 (파서 회귀)"
    leaked = keys & set(_LEGACY_PARAM_KEYS)
    assert not leaked, f"guide 예제가 legacy 키를 사용: {sorted(leaked)}"


def test_guide_example_keys_are_registry_keys() -> None:
    """guide 예제의 각 dict 키가 레지스트리 정식 키다."""
    keys = _guide_example_param_keys()
    unknown = keys - _REGISTRY_PARAM_KEYS
    assert not unknown, f"guide 예제 키가 레지스트리에 없음: {sorted(unknown)}"


# ── (b) 레지스트리 honored 행위 검증 ─────────────────────────────────────────


@pytest.fixture
def ohlcv_arrays() -> dict[str, np.ndarray]:
    """지표 계산에 충분한 길이의 OHLCV (n=60)."""
    rng = np.random.default_rng(42)
    n = 60
    close = 50000.0 + np.cumsum(rng.normal(0, 100, n))
    high = close + rng.uniform(50, 200, n)
    low = close - rng.uniform(50, 200, n)
    open_ = close + rng.normal(0, 50, n)
    volume = rng.uniform(1000, 10000, n)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _flatten(result: dict[str, np.ndarray]) -> np.ndarray:
    """다중 출력 결과를 단일 1D 배열로 직렬화 (비교용)."""
    return np.concatenate([np.asarray(v, dtype=float).ravel() for v in result.values()])


def _override_value(key: str, default: object) -> object:
    """레지스트리 기본값과 확실히 다른 override 값을 만든다.

    정수 기간 파라미터는 **줄이는** 방향으로 바꾼다. 늘리면 lookback이 커져
    고정 길이 OHLCV로는 pandas-ta가 None을 반환(데이터 부족)할 수 있어
    silent-drop과 구분되지 않기 때문이다. 최소 2 이상은 보장한다.
    """
    if isinstance(default, bool):
        return not default
    if isinstance(default, int):
        return max(2, default - 3)
    if isinstance(default, float):
        return default + 3.0
    raise AssertionError(f"unexpected default type for {key}: {type(default)}")


# params를 가진 모든 지표 × 각 레지스트리 키 조합을 파라미터화.
_HONOR_CASES = [
    (name, key, default)
    for name, spec in sorted(INDICATOR_REGISTRY.items())
    for key, default in spec["params"].items()
]


@pytest.mark.parametrize(
    ("name", "key", "default"),
    _HONOR_CASES,
    ids=[f"{n}-{k}" for n, k, _ in _HONOR_CASES],
)
def test_registry_param_is_honored(
    name: str,
    key: str,
    default: object,
    ohlcv_arrays: dict[str, np.ndarray],
) -> None:
    """각 레지스트리 키를 비기본값으로 전달하면 결과가 기본과 달라진다.

    silent-drop(예: bbands ``std``)을 직접 검출한다. 키가 honored면 비기본값
    전달 시 출력이 변해야 한다.
    """
    baseline = IndicatorCalculator.compute(name, ohlcv_arrays)
    assert baseline, f"{name} baseline 계산 실패 (데이터 부족?)"

    override = {key: _override_value(key, default)}
    changed = IndicatorCalculator.compute(name, ohlcv_arrays, **override)
    assert changed, f"{name} {key} override 계산 실패"

    base_flat = _flatten(baseline)
    changed_flat = _flatten(changed)
    # 출력 형태가 그대로면(키/길이 동일) 값 비교, 다르면 자명히 변경된 것.
    if base_flat.shape == changed_flat.shape:
        differs = not np.allclose(base_flat, changed_flat, equal_nan=True)
    else:
        differs = True
    assert differs, (
        f"{name}의 '{key}={override[key]}' 전달이 기본 출력과 동일 — "
        f"silent-drop 의심 (레지스트리 키가 pandas-ta에 반영되지 않음)"
    )


# ── (c) 가드 동작 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "legacy_key", "hint_fragment"),
    [
        ("rsi", "timeperiod", "length"),
        ("sma", "timeperiod", "length"),
        ("bbands", "nbdev", "lower_std"),
        ("bbands", "std", "lower_std"),
        ("stoch", "fastk", "k"),
        ("stoch", "slowk", "smooth_k"),
        ("stoch", "slowd", "d"),
    ],
)
def test_compute_rejects_legacy_key(
    name: str,
    legacy_key: str,
    hint_fragment: str,
    ohlcv_arrays: dict[str, np.ndarray],
) -> None:
    """블랙리스트 키 전달 시 정정 힌트를 담은 ValueError가 발생한다."""
    with pytest.raises(ValueError) as exc_info:
        IndicatorCalculator.compute(name, ohlcv_arrays, **{legacy_key: 14})
    msg = str(exc_info.value)
    assert legacy_key in msg, f"에러 메시지에 미인식 키 '{legacy_key}' 누락: {msg}"
    assert hint_fragment in msg, (
        f"에러 메시지에 정정 키 힌트 '{hint_fragment}' 누락: {msg}"
    )


def test_compute_accepts_correct_keys(ohlcv_arrays: dict[str, np.ndarray]) -> None:
    """정식 키는 가드를 통과한다 (false-reject 0)."""
    assert IndicatorCalculator.compute("rsi", ohlcv_arrays, length=20)
    assert IndicatorCalculator.compute(
        "bbands", ohlcv_arrays, length=20, lower_std=2.5, upper_std=2.5
    )
    assert IndicatorCalculator.compute("stoch", ohlcv_arrays, k=10, d=3, smooth_k=3)


def test_legacy_keys_not_valid_for_any_indicator() -> None:
    """블랙리스트 키는 어느 지표의 정식 레지스트리 키도 아니다 (전역 거부 안전성)."""
    overlap = set(_LEGACY_PARAM_KEYS) & _REGISTRY_PARAM_KEYS
    assert not overlap, (
        f"블랙리스트 키가 정식 레지스트리 키와 충돌(전역 거부 위험): {sorted(overlap)}"
    )
