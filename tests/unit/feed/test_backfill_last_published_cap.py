"""data.go.kr backfill 상한 cap (미공개 날짜 제외) 검증 (#2015).

data.go.kr OHLCV는 영업일 D의 데이터가 다음 영업일 13:00 KST 이후에 공개된다
(스펙: "영업일 D+1, 오후 1시 이후"). backfill 상한을 KST today 대신 "확실히
공개된 마지막 날짜"(``_last_published_date``)로 cap해, 미공개 최근일을 빈
응답으로 시도하는 quota 낭비를 막는다.

cap은 보조(quota 보호)일 뿐이며 데이터 무결성은 written>0 checkpoint guard가
보장한다. 따라서 cap의 KR 공휴일 미인식 부정확성은 데이터 손실을 유발하지
않는다(빈 응답 → 미전진 → 재시도). 본 테스트는 cap의 deadline 산술과
``_resolve_dates`` 의 상한 전달을 결정적으로(now 주입) 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ante.feed.pipeline import backfill_runner
from ante.feed.pipeline.backfill_runner import (
    BackfillRunner,
    _last_published_date,
    _next_business_day,
)

_KST = timezone(timedelta(hours=9))


def _kst(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=_KST)


class TestNextBusinessDay:
    """``_next_business_day`` (주말 skip, weekday만) 검증."""

    def test_weekday_to_next_weekday(self) -> None:
        # 2026-06-02(화) → 2026-06-03(수)
        assert _next_business_day(date(2026, 6, 2)) == date(2026, 6, 3)

    def test_friday_skips_weekend_to_monday(self) -> None:
        # 2026-05-29(금) → 주말(30 토, 31 일) skip → 2026-06-01(월)
        assert _next_business_day(date(2026, 5, 29)) == date(2026, 6, 1)

    def test_saturday_to_monday(self) -> None:
        # 2026-05-30(토) → 2026-06-01(월)
        assert _next_business_day(date(2026, 5, 30)) == date(2026, 6, 1)


class TestLastPublishedDate:
    """``_last_published_date`` deadline(다음 영업일 13:00 KST) 산술 검증."""

    def test_tuesday_afternoon_returns_monday(self) -> None:
        """화 14:00 → 월.

        어제=월(06-01). 월의 deadline = next_business_day(월)=화(06-02) 13:00.
        14:00 >= 13:00 → 월(06-01)이 확실히 공개됨.
        """
        assert _last_published_date(_kst(2026, 6, 2, 14)) == date(2026, 6, 1)

    def test_tuesday_before_deadline_returns_friday(self) -> None:
        """화 10:00 → 월의 deadline(화 13:00) 미도래 → 직전 영업일 금.

        어제=월(06-01). 월의 deadline=화(06-02) 13:00 > 10:00 → 월 제외.
        다음 후보=일(05-31 비영업)→토(05-30 비영업)→금(05-29 영업).
        금의 deadline = next_business_day(금)=월(06-01) 13:00 <= 화 10:00
        → 금(05-29)이 확실히 공개됨.
        """
        assert _last_published_date(_kst(2026, 6, 2, 10)) == date(2026, 5, 29)

    def test_monday_morning_excludes_friday(self) -> None:
        """월 10:00 → 금요일 제외(다음 영업일 월 13:00 미도래) → 목.

        어제=일(05-31 비영업)→토(05-30 비영업)→금(05-29 영업).
        금의 deadline = next_business_day(금)=월(06-01) 13:00 > 월 10:00
        → 금 제외. 다음 후보=목(05-28). 목의 deadline=금(05-29) 13:00 <=
        월 10:00 → 목(2026-05-28)이 확실히 공개됨.
        """
        assert _last_published_date(_kst(2026, 6, 1, 10)) == date(2026, 5, 28)

    def test_monday_afternoon_includes_friday(self) -> None:
        """월 14:00 → 금(05-29)까지 공개.

        금의 deadline=월(06-01) 13:00 <= 월 14:00 → 금(05-29) 포함.
        """
        assert _last_published_date(_kst(2026, 6, 1, 14)) == date(2026, 5, 29)

    def test_deadline_at_exactly_13_is_inclusive(self) -> None:
        """deadline 정각(13:00)은 공개된 것으로 본다(<= 비교)."""
        # 화 13:00 정각 → 월(06-01)의 deadline(화 13:00)과 동일 → 월 포함.
        assert _last_published_date(_kst(2026, 6, 2, 13)) == date(2026, 6, 1)


class TestResolveDatesCap:
    """``_resolve_dates`` 가 cap된 상한으로 미공개 날짜를 제외하는지 검증."""

    def test_resolve_dates_excludes_unpublished_recent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """checkpoint 없이 backfill 시 미공개 최근일(today/지연공개)이 제외된다.

        now=화 10:00 (2026-06-02 10:00). last_published=금(2026-05-29).
        backfill_since를 2026-05-25(월)로 두면 범위 상한이 today(06-02)가
        아니라 2026-05-29로 cap돼야 한다(06-01 월, 06-02 화 미포함).
        """

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz: timezone | None = None) -> datetime:
                base = _kst(2026, 6, 2, 10)
                return base if tz is None else base.astimezone(tz)

        monkeypatch.setattr(backfill_runner, "datetime", _FixedDatetime)

        feed_dir = tmp_path / ".feed"
        config = {"schedule": {"backfill_since": "2026-05-25"}}
        dates = BackfillRunner._resolve_dates(config, feed_dir)

        # 상한이 2026-05-29(금)로 cap — 미공개 06-01/06-02 미포함.
        assert dates[-1] == "2026-05-29"
        assert "2026-06-01" not in dates
        assert "2026-06-02" not in dates
        # 시작은 backfill_since(2026-05-25) 그대로.
        assert dates[0] == "2026-05-25"

    def test_backfill_since_after_last_published_yields_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """backfill_since > last_published 이면 빈 목록(아직 공개된 날짜 없음)."""

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz: timezone | None = None) -> datetime:
                base = _kst(2026, 6, 2, 10)  # last_published = 2026-05-29
                return base if tz is None else base.astimezone(tz)

        monkeypatch.setattr(backfill_runner, "datetime", _FixedDatetime)

        feed_dir = tmp_path / ".feed"
        # since(2026-06-01) > last_published(2026-05-29) → start > end → empty.
        config = {"schedule": {"backfill_since": "2026-06-01"}}
        dates = BackfillRunner._resolve_dates(config, feed_dir)

        assert dates == []
