"""스케줄러 시간 형식 검증 + loop 순서 테스트 (#2030/#2070/#2031).

- ``_is_valid_hhmm`` / ``_validate_schedule_times``: zero-padded HH:MM 만
  허용. non-padded("9:00")/범위초과("25:00")/구분자없음("1600")/
  "24:00" 등은 거부, 정상("16:00"/"01:00") 통과. blocked_hours 양 끝점도
  검증.
- ``run_scheduler_loop`` 진입 시 1회 fail-fast: 잘못된 시간이면 조용히
  미실행하지 않고 ``ValueError`` 로 즉시 실패.
- loop 순서: backfill_at·daily_at 둘 다 도달한 틱에서 backfill 이 daily
  보다 먼저 실행되며(#2031), 하루 1회 플래그 로직은 보존.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from ante.feed import cli_scheduler
from ante.feed.cli_scheduler import (
    _is_valid_hhmm,
    _validate_schedule_times,
    run_scheduler_loop,
    validate_schedule,
)

_KST = timezone(timedelta(hours=9))
# 자정 무렵 (#2756). 이 시각에 실제 시계를 읽으면 기대값이 어긋났다.
_KST_2359 = datetime(2026, 11, 22, 23, 59, 30, tzinfo=_KST)
_KST_0000 = datetime(2026, 11, 23, 0, 0, 0, tzinfo=_KST)
_KST_0001 = datetime(2026, 11, 23, 0, 1, 0, tzinfo=_KST)
_KST_2358 = datetime(2026, 11, 22, 23, 58, 59, tzinfo=_KST)
_AROUND_MIDNIGHT = [_KST_2359, _KST_0000, _KST_0001]


def _hhmm(value: datetime) -> str:
    return value.strftime("%H:%M")


def _cross_midnight_error(window: str) -> str:
    return (
        f"잘못된 blocked_hours 항목: '{window}' "
        "(시작이 끝보다 늦은 구간은 받지 않습니다 — 자정을 넘으면 "
        "두 구간으로 나눠 적으세요, 예: 23:00-23:59, 00:00-02:00)"
    )


# ── _is_valid_hhmm 단위 ──────────────────────────────────────────────────


class TestIsValidHHMM:
    @pytest.mark.parametrize(
        "value",
        ["00:00", "01:00", "09:00", "16:00", "15:30", "23:59", "12:34"],
    )
    def test_valid_zero_padded(self, value: str) -> None:
        assert _is_valid_hhmm(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "9:00",  # non-padded hour — 사전식 오동작 핵심 케이스 (#2030)
            "09:0",  # non-padded minute
            "25:00",  # hour > 23
            "24:00",  # 24시는 무효 (00:00 만 허용)
            "1600",  # 구분자 없음
            "16:60",  # minute > 59
            "16:5",  # 1자리 minute
            "ab:cd",  # 비숫자
            "16:00 ",  # trailing space
            " 16:00",  # leading space
            "16:00:00",  # 초 포함
            "",  # 빈 문자열
            "-1:00",
        ],
    )
    def test_invalid(self, value: str) -> None:
        assert _is_valid_hhmm(value) is False

    def test_non_string(self) -> None:
        assert _is_valid_hhmm(None) is False  # type: ignore[arg-type]
        assert _is_valid_hhmm(1600) is False  # type: ignore[arg-type]


# ── _validate_schedule_times: daily_at / backfill_at ─────────────────────


class TestValidateScheduleTimes:
    def test_valid_passes(self) -> None:
        # 예외가 발생하지 않으면 통과.
        _validate_schedule_times("16:00", "01:00", ["09:00-15:30"])

    @pytest.mark.parametrize("bad", ["9:00", "25:00", "1600", "24:00"])
    def test_invalid_daily_at_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="daily_at"):
            _validate_schedule_times(bad, "01:00")

    @pytest.mark.parametrize("bad", ["9:00", "25:00", "1600", "24:00"])
    def test_invalid_backfill_at_raises(self, bad: str) -> None:
        with pytest.raises(ValueError, match="backfill_at"):
            _validate_schedule_times("16:00", bad)

    def test_collects_multiple_errors(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _validate_schedule_times("9:00", "25:00")
        msg = str(exc_info.value)
        assert "daily_at" in msg
        assert "backfill_at" in msg

    # ── blocked_hours 형식 ──
    def test_valid_blocked_hours_passes(self) -> None:
        _validate_schedule_times("16:00", "01:00", ["09:00-15:30"])

    def test_empty_blocked_hours_passes(self) -> None:
        _validate_schedule_times("16:00", "01:00", [])
        _validate_schedule_times("16:00", "01:00", None)

    @pytest.mark.parametrize(
        "window",
        [
            "9:00-15:30",  # non-padded start
            "09:00-9:00",  # non-padded end (16:00-9:00 변형)
            "16:00-9:00",  # non-padded end
            "25:00-15:30",  # 범위초과 start
            "09:00-24:00",  # 24:00 end
            "0900-1530",  # 구분자 없음
            "09:00",  # '-' 없음
            "09:00-",  # end 누락
            "-15:30",  # start 누락
        ],
    )
    def test_invalid_blocked_hours_raises(self, window: str) -> None:
        with pytest.raises(ValueError, match="blocked_hours"):
            _validate_schedule_times("16:00", "01:00", [window])

    @pytest.mark.parametrize("window", ["23:00-02:00", "15:31-09:00", "23:59-00:00"])
    def test_cross_midnight_window_rejected(self, window: str) -> None:
        with pytest.raises(ValueError) as exc_info:
            _validate_schedule_times("16:00", "01:00", [window])
        assert str(exc_info.value) == _cross_midnight_error(window)

    def test_ordered_windows_pass(self) -> None:
        _validate_schedule_times(
            "16:00",
            "01:00",
            ["09:00-15:30", "09:00-09:00", "23:00-23:59", "00:00-02:00"],
        )

    def test_format_and_order_errors_are_joined(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _validate_schedule_times("16:00", "01:00", ["25:00-15:30", "23:00-02:00"])
        assert str(exc_info.value) == (
            "잘못된 blocked_hours 항목: '25:00-15:30' "
            "(양 끝점 모두 zero-padded HH:MM 필요, 예: 09:00-15:30); "
            + _cross_midnight_error("23:00-02:00")
        )


class TestValidateSchedule:
    @pytest.mark.parametrize(
        "config",
        [{}, {"guard": "x"}, {"guard": {}}, {"guard": {"blocked_hours": []}}],
    )
    def test_passes_without_blocked_hours(self, config: dict[str, Any]) -> None:
        validate_schedule(config, "16:00", "01:00")

    def test_invalid_blocked_hours_raises(self) -> None:
        with pytest.raises(ValueError, match="잘못된 blocked_hours 항목: '9:00-15:30'"):
            validate_schedule(
                {"guard": {"blocked_hours": ["9:00-15:30"]}}, "16:00", "01:00"
            )

    def test_invalid_daily_at_raises(self) -> None:
        with pytest.raises(ValueError, match="잘못된 daily_at 형식: '25:00'"):
            validate_schedule({}, "25:00", "01:00")

    def test_cross_midnight_blocked_hours_raises(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            validate_schedule(
                {"guard": {"blocked_hours": ["23:00-02:00"]}}, "16:00", "01:00"
            )
        assert str(exc_info.value) == _cross_midnight_error("23:00-02:00")


# ── run_scheduler_loop 진입 fail-fast ────────────────────────────────────


class TestSchedulerLoopFailFast:
    def test_invalid_daily_at_fails_fast_not_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """non-padded daily_at("9:00") → 조용한 미실행이 아니라 ValueError."""
        ran: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            ran.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            ran.append("backfill")

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)

        with pytest.raises(ValueError, match="daily_at"):
            asyncio.run(
                run_scheduler_loop(
                    orchestrator=MagicMock(),
                    data_path="data/",
                    config={},
                    daily_at="9:00",
                    backfill_at="01:00",
                )
            )
        # 검증은 루프 진입 전이므로 작업이 실행되지 않는다.
        assert ran == []

    def test_invalid_backfill_at_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="backfill_at"):
            asyncio.run(
                run_scheduler_loop(
                    orchestrator=MagicMock(),
                    data_path="data/",
                    config={},
                    daily_at="16:00",
                    backfill_at="25:00",
                )
            )

    def test_invalid_blocked_hours_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="blocked_hours"):
            asyncio.run(
                run_scheduler_loop(
                    orchestrator=MagicMock(),
                    data_path="data/",
                    config={"guard": {"blocked_hours": ["9:00-15:30"]}},
                    daily_at="16:00",
                    backfill_at="01:00",
                )
            )

    def test_cross_midnight_blocked_hours_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ran: list[str] = []

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            ran.append("backfill")

        async def _instant_wait(stop_event: asyncio.Event, *, timeout: float) -> None:
            stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _instant_wait)
        with pytest.raises(ValueError) as exc_info:
            asyncio.run(
                run_scheduler_loop(
                    orchestrator=MagicMock(),
                    data_path="data/",
                    config={"guard": {"blocked_hours": ["23:00-02:00"]}},
                    daily_at="16:00",
                    backfill_at="01:00",
                )
            )
        assert str(exc_info.value) == _cross_midnight_error("23:00-02:00")
        assert ran == []


# ── loop 순서: backfill 우선 (#2031) ─────────────────────────────────────


class TestSchedulerLoopOrder:
    def test_backfill_runs_before_daily_when_both_due(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """둘 다 도달한 1틱: backfill 이 daily 보다 먼저 호출된다."""
        call_order: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            call_order.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            call_order.append("backfill")

        async def _instant_wait(stop_event: asyncio.Event, *, timeout: float) -> None:
            # 첫 틱 이후 루프를 종료시킨다.
            stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _instant_wait)

        # 둘 다 과거 시각이라 같은 틱에서 모두 도달.
        asyncio.run(
            run_scheduler_loop(
                orchestrator=MagicMock(),
                data_path="data/",
                config={},
                daily_at="00:00",
                backfill_at="00:00",
            )
        )

        assert call_order == ["backfill", "daily"]

    @pytest.mark.parametrize(
        "manual_clock", [_KST_2358, _KST_0000, _KST_0001], indirect=True, ids=_hhmm
    )
    def test_daily_at_in_future_only_backfill_runs(
        self, monkeypatch: pytest.MonkeyPatch, manual_clock
    ) -> None:
        """daily_at 미도달이면 backfill 만 실행(daily 플래그/시각 조건 보존).

        시계를 고정한다(#2756). 실제 시계로는 KST 23:59에 daily_at="23:59"가
        도달해 실패했다.
        """
        call_order: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            call_order.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            call_order.append("backfill")

        async def _instant_wait(stop_event: asyncio.Event, *, timeout: float) -> None:
            stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _instant_wait)

        asyncio.run(
            run_scheduler_loop(
                orchestrator=MagicMock(),
                data_path="data/",
                config={},
                daily_at="23:59",
                backfill_at="00:00",
            )
        )

        assert call_order == ["backfill"]

    @pytest.mark.parametrize("manual_clock", [_KST_2359], indirect=True, ids=_hhmm)
    def test_daily_at_reached_at_2359_runs_daily(
        self, monkeypatch: pytest.MonkeyPatch, manual_clock
    ) -> None:
        """KST 23:59에는 daily_at="23:59"가 도달해 daily도 돈다(#2756의 원인)."""
        call_order: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            call_order.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            call_order.append("backfill")

        async def _instant_wait(stop_event: asyncio.Event, *, timeout: float) -> None:
            stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _instant_wait)

        asyncio.run(
            run_scheduler_loop(
                orchestrator=MagicMock(),
                data_path="data/",
                config={},
                daily_at="23:59",
                backfill_at="00:00",
            )
        )

        assert call_order == ["backfill", "daily"]

    @pytest.mark.parametrize("manual_clock", _AROUND_MIDNIGHT, indirect=True, ids=_hhmm)
    def test_each_job_runs_once_per_day(
        self, monkeypatch: pytest.MonkeyPatch, manual_clock
    ) -> None:
        """하루 1회 플래그 로직 회귀: 여러 틱이어도 각 1회만 실행.

        시계를 고정하므로 틱 사이에 날짜가 바뀌지 않는다(#2756).
        """
        call_order: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            call_order.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            call_order.append("backfill")

        ticks = {"n": 0}

        async def _wait_three_ticks(
            stop_event: asyncio.Event, *, timeout: float
        ) -> None:
            ticks["n"] += 1
            if ticks["n"] >= 3:
                stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _wait_three_ticks)

        asyncio.run(
            run_scheduler_loop(
                orchestrator=MagicMock(),
                data_path="data/",
                config={},
                daily_at="00:00",
                backfill_at="00:00",
            )
        )

        assert call_order.count("backfill") == 1
        assert call_order.count("daily") == 1
        # 첫 틱에서 backfill 이 daily 보다 먼저.
        assert call_order == ["backfill", "daily"]

    @pytest.mark.parametrize("manual_clock", [_KST_2359], indirect=True, ids=_hhmm)
    def test_flags_reset_when_date_changes_between_ticks(
        self, monkeypatch: pytest.MonkeyPatch, manual_clock
    ) -> None:
        """틱 사이에 날짜가 바뀌면 플래그가 풀려 새 날에 다시 돈다(#2756)."""
        call_order: list[str] = []

        async def _track_daily(*_a: Any, **_k: Any) -> None:
            call_order.append("daily")

        async def _track_backfill(*_a: Any, **_k: Any) -> None:
            call_order.append("backfill")

        ticks = {"n": 0}

        async def _wait_one_minute(
            stop_event: asyncio.Event, *, timeout: float
        ) -> None:
            ticks["n"] += 1
            manual_clock.advance(timeout)
            if ticks["n"] >= 2:
                stop_event.set()

        monkeypatch.setattr(cli_scheduler, "_run_daily_job", _track_daily)
        monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _track_backfill)
        monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _wait_one_minute)

        asyncio.run(
            run_scheduler_loop(
                orchestrator=MagicMock(),
                data_path="data/",
                config={},
                daily_at="00:00",
                backfill_at="00:00",
            )
        )

        assert call_order == ["backfill", "daily", "backfill", "daily"]
