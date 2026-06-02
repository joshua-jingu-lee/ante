"""Scheduler 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone

import pytest

from ante.feed.pipeline import scheduler
from ante.feed.pipeline.scheduler import (
    generate_backfill_dates,
    generate_daily_date,
    is_business_day,
)


class _FakeDatetime:
    """scheduler 모듈의 datetime을 대체해 now()를 고정한다.

    실제 tzinfo 변환을 보존하기 위해 fixed UTC 시각에 대해 정상적인
    astimezone 변환을 수행한다. (OS local TZ와 무관하게 결정적.)
    """

    _fixed_utc: datetime

    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        if tz is None:
            return cls._fixed_utc
        return cls._fixed_utc.astimezone(tz)


class TestGenerateBackfillDates:
    """backfill 날짜 범위 생성 테스트."""

    def test_basic_range(self) -> None:
        """시작~종료 범위의 모든 날짜를 생성한다."""
        dates = list(generate_backfill_dates("2024-01-01", "2024-01-05"))
        assert dates == [
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]

    def test_single_day_range(self) -> None:
        """시작과 종료가 같으면 1일만 생성한다."""
        dates = list(generate_backfill_dates("2024-01-01", "2024-01-01"))
        assert dates == ["2024-01-01"]

    def test_empty_when_start_after_end(self) -> None:
        """시작이 종료보다 크면 빈 결과를 반환한다."""
        dates = list(generate_backfill_dates("2024-01-10", "2024-01-05"))
        assert dates == []

    def test_explicit_end_is_used_verbatim(self) -> None:
        """명시 end 인자가 주어지면 KST today와 무관하게 그대로 사용한다(회귀)."""
        dates = list(generate_backfill_dates("2026-01-01", end="2026-01-05"))
        assert dates == [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
        ]

    def test_end_defaults_to_kst_today(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """end가 None이면 KST 기준 오늘을 종료일로 사용한다(OS TZ 무관).

        UTC 2026-01-01 23:30 = KST 2026-01-02 08:30 이므로 KST today는
        2026-01-02 여야 한다. OS local date.today()였다면 UTC 환경에서
        2026-01-01 로 어긋난다.
        """
        _FakeDatetime._fixed_utc = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
        monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)

        # KST today == 2026-01-02. 시작일을 그 날로 두면 end 기본값도
        # 2026-01-02 이므로 단일 날짜만 생성된다.
        dates = list(generate_backfill_dates("2026-01-02"))
        assert dates == ["2026-01-02"]

        # UTC today(2026-01-01)였다면 start(2026-01-02) > end(2026-01-01)로
        # 빈 결과가 되었을 것이다. KST 적용으로 비어있지 않음을 추가 확인.
        assert dates != []

    def test_includes_weekends(self) -> None:
        """영업일 필터링 없이 주말도 포함한다."""
        # 2024-01-06 = 토요일, 2024-01-07 = 일요일
        dates = list(generate_backfill_dates("2024-01-05", "2024-01-08"))
        assert "2024-01-06" in dates
        assert "2024-01-07" in dates


class TestBackfillWithCheckpoint:
    """체크포인트를 사용한 backfill 재개 테스트."""

    def test_resume_from_checkpoint(self) -> None:
        """체크포인트 다음 날부터 시작한다."""
        dates = list(
            generate_backfill_dates(
                "2024-01-01",
                "2024-01-05",
                last_checkpoint="2024-01-03",
            )
        )
        assert dates == ["2024-01-04", "2024-01-05"]

    def test_checkpoint_at_end_returns_empty(self) -> None:
        """체크포인트가 종료일과 같으면 빈 결과를 반환한다."""
        dates = list(
            generate_backfill_dates(
                "2024-01-01",
                "2024-01-05",
                last_checkpoint="2024-01-05",
            )
        )
        assert dates == []

    def test_checkpoint_after_end_returns_empty(self) -> None:
        """체크포인트가 종료일 이후면 빈 결과를 반환한다."""
        dates = list(
            generate_backfill_dates(
                "2024-01-01",
                "2024-01-05",
                last_checkpoint="2024-01-10",
            )
        )
        assert dates == []

    def test_checkpoint_before_start(self) -> None:
        """체크포인트가 시작일 이전이면 시작일부터 생성한다."""
        dates = list(
            generate_backfill_dates(
                "2024-01-05",
                "2024-01-07",
                last_checkpoint="2024-01-02",
            )
        )
        assert dates == ["2024-01-05", "2024-01-06", "2024-01-07"]

    def test_checkpoint_none_starts_from_begin(self) -> None:
        """체크포인트가 None이면 시작일부터 생성한다."""
        dates = list(
            generate_backfill_dates(
                "2024-01-01",
                "2024-01-03",
                last_checkpoint=None,
            )
        )
        assert dates == ["2024-01-01", "2024-01-02", "2024-01-03"]


class TestGenerateDailyDate:
    """daily 수집 날짜 생성 테스트."""

    def test_returns_yesterday(self) -> None:
        """기준일의 전일을 반환한다."""
        result = generate_daily_date(date(2024, 3, 15))
        assert result == "2024-03-14"

    def test_returns_yesterday_across_month(self) -> None:
        """월 경계를 넘어도 정확한 전일을 반환한다."""
        result = generate_daily_date(date(2024, 3, 1))
        assert result == "2024-02-29"  # 2024년은 윤년

    def test_returns_yesterday_across_year(self) -> None:
        """연도 경계를 넘어도 정확한 전일을 반환한다."""
        result = generate_daily_date(date(2024, 1, 1))
        assert result == "2023-12-31"

    def test_explicit_reference_is_used_verbatim(self) -> None:
        """명시 reference 인자가 주어지면 KST today와 무관하게 그대로 사용한다(회귀)."""
        result = generate_daily_date(reference=date(2026, 1, 5))
        assert result == "2026-01-04"

    def test_default_reference_is_kst_today(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """기준일 미지정 시 KST 기준 오늘의 전일을 반환한다(OS TZ 무관).

        UTC 2026-01-01 23:30 = KST 2026-01-02 08:30 이므로 KST today는
        2026-01-02, 전일은 2026-01-01 이다. OS local date.today()였다면
        UTC 환경에서 today=2026-01-01, 전일=2025-12-31 로 어긋난다.
        """
        _FakeDatetime._fixed_utc = datetime(2026, 1, 1, 23, 30, tzinfo=UTC)
        monkeypatch.setattr(scheduler, "datetime", _FakeDatetime)

        assert generate_daily_date() == "2026-01-01"

    def test_return_format_is_iso(self) -> None:
        """반환값은 YYYY-MM-DD 형식이다."""
        result = generate_daily_date(date(2024, 6, 15))
        assert len(result) == 10
        assert result[4] == "-"
        assert result[7] == "-"


class TestIsBusinessDay:
    """영업일 판별 테스트."""

    def test_monday_is_business_day(self) -> None:
        """월요일은 영업일이다."""
        assert is_business_day("2024-01-01") is True  # 월요일

    def test_friday_is_business_day(self) -> None:
        """금요일은 영업일이다."""
        assert is_business_day("2024-01-05") is True  # 금요일

    def test_saturday_is_not_business_day(self) -> None:
        """토요일은 영업일이 아니다."""
        assert is_business_day("2024-01-06") is False  # 토요일

    def test_sunday_is_not_business_day(self) -> None:
        """일요일은 영업일이 아니다."""
        assert is_business_day("2024-01-07") is False  # 일요일

    def test_all_weekdays(self) -> None:
        """월~금은 모두 영업일이다."""
        # 2024-01-01(월) ~ 2024-01-05(금)
        for day in range(1, 6):
            assert is_business_day(f"2024-01-0{day}") is True

    def test_weekend_pair(self) -> None:
        """토~일은 모두 비영업일이다."""
        assert is_business_day("2024-01-06") is False
        assert is_business_day("2024-01-07") is False
