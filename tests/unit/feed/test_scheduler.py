"""Scheduler 모듈 단위 테스트."""

from __future__ import annotations

from datetime import date

from ante.feed.pipeline.scheduler import (
    generate_backfill_dates,
    generate_daily_date,
    is_business_day,
)


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

    def test_end_defaults_to_today(self) -> None:
        """end가 None이면 오늘까지 생성한다."""
        today = date.today().isoformat()
        dates = list(generate_backfill_dates(today))
        assert dates == [today]

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

    def test_default_reference_is_today(self) -> None:
        """기준일 미지정 시 오늘 기준으로 전일을 반환한다."""
        from datetime import timedelta

        expected = (date.today() - timedelta(days=1)).isoformat()
        assert generate_daily_date() == expected

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
