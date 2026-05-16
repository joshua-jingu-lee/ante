"""Unit tests — `ante.core.market_data_vocab` SSOT (#1613).

본 모듈은 두 가지를 못 박는다:
  1. SSOT 모듈 자체의 불변식 (canonical timeframe 값·순서·타입,
     exact-literal·no-alias·no-normalization 검증 헬퍼, KRX symbol
     fullmatch 엄격도 — R1-F1).
  2. 위임 후 behavior-preserving 회귀 — `data.schemas.TIMEFRAMES`
     (타입 `list`·순서 불변), `data.retention._OHLCV_TIMEFRAMES`/
     `DEFAULT_RETENTION` (drift 계약), `rule.engine` KRX preflight
     (#1299 fail-closed 불변), `data.store` legacy migration (축 E
     `\\d` Unicode 보존 — R1-F2 timeframe 무필터).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ante.core.market_data_vocab import (
    CANONICAL_TIMEFRAMES,
    TIMEFRAME_SET,
    is_krx_symbol,
    is_valid_timeframe,
)


class TestCanonicalTimeframes:
    """canonical timeframe 고정 집합·고정 순서·타입 (core.md
    ``### Canonical timeframe set``)."""

    def test_canonical_timeframes_exact_value_and_order(self):
        # 고정 순서: 1m → 5m → 15m → 1h → 1d (순서 의존 소비자 계약).
        assert CANONICAL_TIMEFRAMES == ("1m", "5m", "15m", "1h", "1d")

    def test_canonical_timeframes_is_tuple(self):
        # 순서가 의미를 가지므로 tuple 이어야 한다.
        assert isinstance(CANONICAL_TIMEFRAMES, tuple)

    def test_timeframe_set_value(self):
        assert TIMEFRAME_SET == frozenset({"1m", "5m", "15m", "1h", "1d"})
        assert TIMEFRAME_SET == frozenset(CANONICAL_TIMEFRAMES)

    def test_timeframe_set_is_frozenset(self):
        assert isinstance(TIMEFRAME_SET, frozenset)

    def test_timeframe_set_immutable(self):
        with pytest.raises(AttributeError):
            TIMEFRAME_SET.add("2h")  # type: ignore[attr-defined]


class TestIsValidTimeframe:
    """``is_valid_timeframe`` — exact-literal, no-alias, no-normalization."""

    @pytest.mark.parametrize("value", ["1m", "5m", "15m", "1h", "1d"])
    def test_canonical_values_true(self, value):
        assert is_valid_timeframe(value) is True

    @pytest.mark.parametrize(
        "value",
        # alias·대소문자·subminute(축 B)·fundamental cadence(축 F)·빈값
        [
            "1min",
            "D",
            "daily",
            "1D",
            "1H",
            "1M",
            "10s",
            "30s",
            "quarterly",
            "annual",
            "",
            " 1m",
            "1m ",
        ],
        ids=[
            "alias-1min",
            "alias-D",
            "alias-daily",
            "uppercase-1D",
            "uppercase-1H",
            "uppercase-1M",
            "subminute-10s",
            "subminute-30s",
            "cadence-quarterly",
            "cadence-annual",
            "empty",
            "leading-space",
            "trailing-space",
        ],
    )
    def test_non_canonical_values_false(self, value):
        assert is_valid_timeframe(value) is False


class TestIsKrxSymbol:
    """``is_krx_symbol`` — fullmatch 엄격도 (R1-F1), ASCII-only, non-str 안전."""

    @pytest.mark.parametrize("value", ["005930", "069500", "000660", "123456"])
    def test_valid_six_digit_ascii_true(self, value):
        assert is_krx_symbol(value) is True

    @pytest.mark.parametrize(
        "value",
        ["12345", "1234567", "05A123", "AAPL", "", "12-456"],
        ids=["too-short", "too-long", "alpha-mixed", "non-numeric", "empty", "hyphen"],
    )
    def test_invalid_shape_false(self, value):
        assert is_krx_symbol(value) is False

    def test_unicode_digit_rejected(self):
        # 신규 입력은 ASCII `[0-9]` 만 허용 — 전각 Unicode digit 거부.
        # (legacy migration `\\d` Unicode 판별과 별개 축 — store.py 보존.)
        assert is_krx_symbol("１２３４５６") is False

    @pytest.mark.parametrize(
        "value",
        ["123456\n", "\n123456", "123456\t", " 005930", "005930 ", "  005930  "],
        ids=[
            "trailing-newline",
            "leading-newline",
            "trailing-tab",
            "leading-space",
            "trailing-space",
            "surrounding-space",
        ],
    )
    def test_fullmatch_rejects_whitespace_padding(self, value):
        # R1-F1: `^...$`+`re.match` 는 `123456\n` 을 통과시키므로(#1299
        # fail-closed 회귀) helper 는 `\\A...\\Z`+`fullmatch` 엄격도여야 한다.
        assert is_krx_symbol(value) is False

    @pytest.mark.parametrize(
        "value",
        [None, 123456, 5930.0, [], {}, set(), b"005930", True],
        ids=["none", "int", "float", "list", "dict", "set", "bytes", "bool"],
    )
    def test_non_str_input_safe_false(self, value):
        # 비문자열은 `re` TypeError 없이 isinstance 선검사로 False.
        assert is_krx_symbol(value) is False  # type: ignore[arg-type]


class TestSchemasTimeframesDelegation:
    """`data.schemas.TIMEFRAMES` 가 SSOT 위임 — 타입 `list`·순서 불변."""

    def test_timeframes_value_and_order(self):
        from ante.data.schemas import TIMEFRAMES

        # 위임 전 값·순서 그대로 (순서 의존 소비자 cli/commands/data.py 보존).
        assert TIMEFRAMES == ["1m", "5m", "15m", "1h", "1d"]
        assert TIMEFRAMES == list(CANONICAL_TIMEFRAMES)

    def test_timeframes_type_preserved(self):
        from ante.data.schemas import TIMEFRAMES

        # 위임 전 타입(mutable list[str])을 그대로 유지한다.
        assert type(TIMEFRAMES) is list

    def test_timeframes_independent_list_instance(self):
        # `list(...)` 파생이므로 SSOT tuple 과 분리된 인스턴스여야 한다
        # (소비자가 mutate 해도 SSOT 불변).
        from ante.data.schemas import TIMEFRAMES

        assert TIMEFRAMES is not CANONICAL_TIMEFRAMES


class TestRetentionDelegation:
    """`data.retention` 위임 + `DEFAULT_RETENTION` drift 계약."""

    def test_ohlcv_timeframes_delegates_to_ssot(self):
        from ante.data.retention import _OHLCV_TIMEFRAMES

        assert _OHLCV_TIMEFRAMES is TIMEFRAME_SET
        assert _OHLCV_TIMEFRAMES == frozenset({"1m", "5m", "15m", "1h", "1d"})

    def test_default_retention_key_drift_contract(self):
        # 보존 기간 수치는 retention 정책 고유지만, timeframe key 집합은
        # SSOT 와 drift 하면 안 된다 (core.md 소비자 매핑 #1613).
        from ante.data.retention import RetentionPolicy

        assert set(RetentionPolicy.DEFAULT_RETENTION) == TIMEFRAME_SET | {"fundamental"}

    def test_default_retention_values_unchanged(self):
        # 위임은 behavior-preserving — 보존 기간 수치 불변.
        from ante.data.retention import RetentionPolicy

        assert RetentionPolicy.DEFAULT_RETENTION == {
            "1m": 365,
            "5m": 365,
            "15m": 365,
            "1h": 365,
            "1d": 3650,
            "fundamental": -1,
        }

    def test_resolve_data_type_behavior_unchanged(self):
        from ante.data.retention import _resolve_data_type

        assert _resolve_data_type("1m") == ("ohlcv", "1m")
        assert _resolve_data_type("1d") == ("ohlcv", "1d")
        assert _resolve_data_type("fundamental") == ("fundamental", "")
        # non-canonical key 는 ohlcv 가 아님 (위임 전후 동일).
        assert _resolve_data_type("2h") == ("2h", "")


class TestStoreLegacyMigrationAxisE:
    """store.py legacy `\\d` migration 보존 (축 E) — R1-F2 timeframe 무필터."""

    def test_legacy_pattern_preserves_unicode_digit(self):
        # 신규 입력 SSOT 로 위임하지 않고 legacy `\\d`(Unicode) 보존.
        from ante.data.store import _LEGACY_KRX_SYMBOL_PATTERN

        assert _LEGACY_KRX_SYMBOL_PATTERN.match("005930") is not None
        # `\\d` 는 전각 Unicode digit 도 매치 (신규 입력 ASCII 와 별개 축).
        assert _LEGACY_KRX_SYMBOL_PATTERN.match("１２３４５６") is not None

    def test_legacy_pattern_distinct_from_ssot(self):
        # 축 E 분리: legacy 판별은 신규 입력 ASCII fullmatch 와 의미가 다르다.
        from ante.data.store import _LEGACY_KRX_SYMBOL_PATTERN

        assert _LEGACY_KRX_SYMBOL_PATTERN.match("１２３４５６") is not None
        assert is_krx_symbol("１２３４５６") is False

    def test_migrate_unicode_digit_legacy_dir_still_moved(self, tmp_path: Path):
        # (a) 6자리 Unicode-digit legacy dir 이 여전히 KRX/ 로 이동.
        from ante.data.store import migrate_parquet_paths

        old_path = tmp_path / "ohlcv" / "1d" / "１２３４５６"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 1
        assert not old_path.exists()
        new_path = tmp_path / "ohlcv" / "1d" / "KRX" / "１２３４５６"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").exists()

    def test_migrate_non_canonical_timeframe_legacy_dir_still_moved(
        self, tmp_path: Path
    ):
        # (b) R1-F2: `ohlcv/<non-canonical_tf>/<6digit>/` legacy dir 도
        # 여전히 KRX/ 로 이동 — migrate_parquet_paths 가 timeframe dir 을
        # TIMEFRAME_SET/canonical 로 필터하지 않음을 잠근다 (필터 추가 시
        # exchange-less 위치에 silent 잔존 → read 비가시 회귀).
        from ante.data.store import migrate_parquet_paths

        old_path = tmp_path / "ohlcv" / "2h" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 1
        assert not old_path.exists()
        new_path = tmp_path / "ohlcv" / "2h" / "KRX" / "005930"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").exists()
