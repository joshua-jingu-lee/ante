"""``validate_dataset_filters``의 fundamental+timeframe 모순 거부 (#1983).

``test_data_success_output_drift.py``를 지울 때(#2773) 그 파일에서 그대로
옮겼다. CLI 경계의 ``DATA_INVALID_FILTER`` 매핑은
``tests/unit/cli/test_backtest_data_instrument_error_exits.py``가 잠근다.

fundamental 데이터셋은 timeframe="" 으로 저장되며 timeframe 차원이 없다.
precedence: ① timeframe vocabulary → ② data_type 유효성 → ③ fundamental+
timeframe 모순 거부.
"""

from __future__ import annotations

import pytest


class TestValidateDatasetFiltersFundamentalTimeframe:
    """``validate_dataset_filters`` fundamental+timeframe 모순 거부 단위 (#1983)."""

    def test_fundamental_with_timeframe_rejected(self) -> None:
        """(a) 재현: fundamental + 유효 timeframe → ValueError 거부."""
        from ante.data.datasets import validate_dataset_filters

        with pytest.raises(ValueError) as exc_info:
            validate_dataset_filters(data_type="fundamental", timeframe="1d")
        # 모순 거부 메시지 (vocabulary 메시지가 아님 — precedence 통과 후).
        assert "fundamental" in str(exc_info.value)
        assert "timeframe" in str(exc_info.value)
        assert "허용되지 않은 timeframe" not in str(exc_info.value)

    def test_fundamental_without_timeframe_returns_fundamental(self) -> None:
        """(b) 회귀: fundamental + timeframe 미지정 → "fundamental" 정상 반환."""
        from ante.data.datasets import validate_dataset_filters

        assert (
            validate_dataset_filters(data_type="fundamental", timeframe=None)
            == "fundamental"
        )

    def test_ohlcv_with_timeframe_returns_ohlcv(self) -> None:
        """(c) 회귀: ohlcv + 유효 timeframe → "ohlcv" 정상 반환 (거부 안 함)."""
        from ante.data.datasets import validate_dataset_filters

        assert validate_dataset_filters(data_type="ohlcv", timeframe="1d") == "ohlcv"

    def test_fundamental_with_invalid_timeframe_hits_vocabulary_first(self) -> None:
        """(d) 회귀: fundamental + 비-canonical timeframe → vocabulary error 우선.

        precedence ① (timeframe vocabulary) 가 ③ (모순 거부) 보다 먼저 평가되어,
        invalid timeframe 메시지("허용되지 않은 timeframe")가 반환되어야 한다.
        """
        from ante.data.datasets import validate_dataset_filters

        with pytest.raises(ValueError) as exc_info:
            validate_dataset_filters(data_type="fundamental", timeframe="invalid")
        assert "허용되지 않은 timeframe" in str(exc_info.value)

    def test_timeframe_only_without_data_type_returns_none(self) -> None:
        """(e) 회귀: data_type 미지정 + timeframe → None 반환 (비목표, 기존 동작).

        data_type=None + timeframe 조합은 별개 contract (Non-Goal) 이므로
        기존대로 None 을 반환하며 모순 거부 대상이 아니다.
        """
        from ante.data.datasets import validate_dataset_filters

        assert validate_dataset_filters(timeframe="1d") is None
