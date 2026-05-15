"""Unit tests — `ante.core.exchange` canonical exchange vocabulary SSOT (#1576).

본 모듈은 두 가지를 못 박는다:
  1. SSOT 모듈 자체의 불변식 (집합 값/`*` 정책/exact-literal 검증 헬퍼).
  2. 위임 후 zero-change 회귀 — strategy validator `VALID_EXCHANGES`와
     data store `_KNOWN_EXCHANGES`가 SSOT와 동일 값이며 검증 결과·에러
     메시지 문자열이 위임 전과 완전히 동일하다.
"""

from __future__ import annotations

import pytest

from ante.core.exchange import (
    CANONICAL_EXCHANGES,
    STRATEGY_EXCHANGES,
    STRATEGY_WILDCARD,
    is_canonical,
    is_strategy_allowed,
    normalize_exchange,
)


class TestCanonicalSet:
    """canonical 5종 집합 불변식 (core.md ``### Canonical set``)."""

    def test_canonical_exchanges_exact_value(self):
        assert CANONICAL_EXCHANGES == frozenset(
            {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST"}
        )

    def test_canonical_exchanges_is_frozenset(self):
        assert isinstance(CANONICAL_EXCHANGES, frozenset)

    def test_canonical_exchanges_immutable(self):
        with pytest.raises(AttributeError):
            CANONICAL_EXCHANGES.add("LSE")  # type: ignore[attr-defined]

    def test_wildcard_is_not_canonical(self):
        assert STRATEGY_WILDCARD == "*"
        assert STRATEGY_WILDCARD not in CANONICAL_EXCHANGES


class TestStrategyExchanges:
    """strategy 표면 집합 = canonical ∪ {`*`} (core.md ``### Wildcard 정책``)."""

    def test_strategy_exchanges_exact_value(self):
        assert STRATEGY_EXCHANGES == CANONICAL_EXCHANGES | {"*"}
        assert STRATEGY_EXCHANGES == frozenset(
            {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"}
        )

    def test_strategy_exchanges_is_frozenset(self):
        assert isinstance(STRATEGY_EXCHANGES, frozenset)

    def test_strategy_superset_of_canonical(self):
        assert CANONICAL_EXCHANGES < STRATEGY_EXCHANGES
        assert STRATEGY_EXCHANGES - CANONICAL_EXCHANGES == {"*"}


class TestIsCanonical:
    """``is_canonical`` — exact-literal, 대소문자/별칭 정규화 없음."""

    @pytest.mark.parametrize("value", ["KRX", "NYSE", "NASDAQ", "AMEX", "TEST"])
    def test_canonical_values_true(self, value):
        assert is_canonical(value) is True

    def test_wildcard_is_not_canonical(self):
        assert is_canonical("*") is False

    @pytest.mark.parametrize(
        "value", ["krx", "Krx", "nyse", "LSE", "ORACLE_INVALID_EXCHANGE", "", " KRX"]
    )
    def test_non_canonical_values_false(self, value):
        assert is_canonical(value) is False


class TestIsStrategyAllowed:
    """``is_strategy_allowed`` — canonical ∪ {`*`}, exact-literal."""

    @pytest.mark.parametrize("value", ["KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"])
    def test_allowed_values_true(self, value):
        assert is_strategy_allowed(value) is True

    @pytest.mark.parametrize(
        "value", ["krx", "LSE", "ORACLE_INVALID_EXCHANGE", "", "**"]
    )
    def test_disallowed_values_false(self, value):
        assert is_strategy_allowed(value) is False


class TestNormalizeExchange:
    """``normalize_exchange`` — exact-literal passthrough, 변환 금지 (q5)."""

    @pytest.mark.parametrize(
        "value",
        ["KRX", "krx", "Krx", "*", "LSE", "ORACLE_INVALID_EXCHANGE", "", " KRX "],
    )
    def test_passthrough_no_transform(self, value):
        # 대소문자 정규화/별칭/trim 등 어떤 변환도 하지 않는다.
        assert normalize_exchange(value) == value
        assert normalize_exchange(value) is value


class TestStrategyValidatorDelegation:
    """strategy validator가 SSOT에 위임 — 값·에러 메시지 zero-change."""

    def test_valid_exchanges_delegates_to_ssot(self):
        from ante.strategy.validator import VALID_EXCHANGES

        # 이름 그대로 유지 + 값은 SSOT(STRATEGY_EXCHANGES)와 동치.
        assert VALID_EXCHANGES == set(STRATEGY_EXCHANGES)
        assert VALID_EXCHANGES == {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"}

    def test_valid_exchanges_type_preserved(self):
        from ante.strategy.validator import VALID_EXCHANGES

        # 위임 전 타입(mutable set[str])을 그대로 유지한다.
        assert type(VALID_EXCHANGES) is set

    def test_valid_exchanges_reexported_from_strategy_package(self):
        import ante.strategy as strategy_pkg

        assert strategy_pkg.VALID_EXCHANGES == {
            "KRX",
            "NYSE",
            "NASDAQ",
            "AMEX",
            "TEST",
            "*",
        }

    def test_validate_exchange_error_messages_unchanged(self):
        """``validate_exchange`` 한국어 에러 메시지 문자열 스냅샷 보존."""
        from ante.strategy.validator import (
            VALID_EXCHANGES,
            validate_exchange,
        )

        with pytest.raises(ValueError) as ei_strategy:
            validate_exchange("INVALID", "KRX")
        assert str(ei_strategy.value) == (
            f"유효하지 않은 전략 exchange: 'INVALID'. "
            f"허용 값: {sorted(VALID_EXCHANGES)}"
        )

        with pytest.raises(ValueError) as ei_account:
            validate_exchange("KRX", "INVALID")
        assert str(ei_account.value) == (
            f"유효하지 않은 계좌 exchange: 'INVALID'. "
            f"허용 값: {sorted(VALID_EXCHANGES - {'*'})}"
        )

        # account 표면은 `*` 거부 (canonical만).
        with pytest.raises(ValueError) as ei_wildcard:
            validate_exchange("KRX", "*")
        assert str(ei_wildcard.value) == (
            f"유효하지 않은 계좌 exchange: '*'. 허용 값: {sorted(CANONICAL_EXCHANGES)}"
        )

    def test_validate_exchange_wildcard_strategy_allowed(self):
        from ante.strategy.validator import validate_exchange

        # `*` 전략은 모든 canonical 계좌와 호환 (raise 없음).
        for acct in sorted(CANONICAL_EXCHANGES):
            validate_exchange("*", acct)


class TestDataStoreDelegation:
    """data store `_KNOWN_EXCHANGES`가 SSOT에 위임 — 값 zero-change."""

    def test_known_exchanges_is_canonical_set(self):
        from ante.data.store import _KNOWN_EXCHANGES

        assert _KNOWN_EXCHANGES is CANONICAL_EXCHANGES
        assert _KNOWN_EXCHANGES == frozenset({"KRX", "NYSE", "NASDAQ", "AMEX", "TEST"})
