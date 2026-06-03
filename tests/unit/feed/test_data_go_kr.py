"""data.go.kr 소스 어댑터 유닛 테스트."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from multidict import CIMultiDict
from yarl import URL

from ante.data.store import ParquetStore
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector
from ante.feed.sources.base import RateLimiter
from ante.feed.sources.data_go_kr import (
    CriticalApiError,
    DailyLimitExceededError,
    DataGoKrError,
    DataGoKrSource,
    ErrorAction,
    classify_error,
)

# ── 테스트 헬퍼 ──────────────────────────────────────────────


def _make_response(
    items: list[dict],
    total_count: int | None = None,
    result_code: str = "00",
    result_msg: str = "NORMAL SERVICE.",
) -> dict:
    """data.go.kr API mock 응답을 생성한다."""
    if total_count is None:
        total_count = len(items)
    return {
        "response": {
            "header": {
                "resultCode": result_code,
                "resultMsg": result_msg,
            },
            "body": {
                "numOfRows": 1000,
                "pageNo": 1,
                "totalCount": total_count,
                "items": {"item": items},
            },
        }
    }


def _make_item(
    bas_dt: str = "20240301",
    srtn_cd: str = "005930",
    itms_nm: str = "삼성전자",
    mrkt_ctg: str = "KOSPI",
    mkp: str = "71000",
    hipr: str = "72000",
    lopr: str = "70500",
    clpr: str = "71500",
    trqu: str = "15000000",
    tr_prc: str = "1072500000000",
    lstg_st_cnt: str = "5969782550",
    mrkt_tot_amt: str = "426839412325000",
) -> dict:
    """data.go.kr API mock item을 생성한다."""
    return {
        "basDt": bas_dt,
        "srtnCd": srtn_cd,
        "isinCd": "KR7005930003",
        "itmsNm": itms_nm,
        "mrktCtg": mrkt_ctg,
        "clpr": clpr,
        "vs": "500",
        "fltRt": "0.70",
        "mkp": mkp,
        "hipr": hipr,
        "lopr": lopr,
        "trqu": trqu,
        "trPrc": tr_prc,
        "lstgStCnt": lstg_st_cnt,
        "mrktTotAmt": mrkt_tot_amt,
    }


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """RateLimiter 인스턴스."""
    return RateLimiter(tps_limit=25.0, daily_limit=10_000)


@pytest.fixture
def source(rate_limiter: RateLimiter) -> DataGoKrSource:
    """DataGoKrSource 인스턴스."""
    return DataGoKrSource(
        api_key="test-api-key",
        rate_limiter=rate_limiter,
        max_retries=2,
    )


# ── classify_error ───────────────────────────────────────────


class TestClassifyError:
    """에러 코드 분류 테스트."""

    def test_normal_service(self) -> None:
        """00은 OK로 분류한다."""
        assert classify_error("00") == ErrorAction.OK

    def test_invalid_parameter(self) -> None:
        """10은 SKIP으로 분류한다."""
        assert classify_error("10") == ErrorAction.SKIP

    def test_daily_limit_exceeded(self) -> None:
        """22는 DAILY_LIMIT으로 분류한다."""
        assert classify_error("22") == ErrorAction.DAILY_LIMIT

    def test_service_key_not_registered(self) -> None:
        """30은 CRITICAL로 분류한다."""
        assert classify_error("30") == ErrorAction.CRITICAL

    def test_deadline_expired(self) -> None:
        """31은 CRITICAL로 분류한다."""
        assert classify_error("31") == ErrorAction.CRITICAL

    def test_unknown_error(self) -> None:
        """99는 RETRY_ONCE로 분류한다 (1회 재시도 후 스킵, #2027)."""
        assert classify_error("99") == ErrorAction.RETRY_ONCE

    def test_application_error_retry(self) -> None:
        """01은 일반 RETRY로 분류한다 (max_retries 유지, 회귀)."""
        assert classify_error("01") == ErrorAction.RETRY

    def test_unmapped_code_defaults_to_retry(self) -> None:
        """매핑되지 않은 코드는 RETRY로 분류한다."""
        assert classify_error("55") == ErrorAction.RETRY


# ── _extract_result_code ─────────────────────────────────────


class TestExtractResultCode:
    """응답 resultCode 추출 테스트."""

    def test_normal_response(self) -> None:
        """정상 응답에서 resultCode를 추출한다."""
        data = _make_response([_make_item()])
        code, msg = DataGoKrSource._extract_result_code(data)
        assert code == "00"
        assert msg == "NORMAL SERVICE."

    def test_error_response(self) -> None:
        """에러 응답에서 resultCode를 추출한다."""
        data = _make_response([], result_code="30", result_msg="KEY_ERROR")
        code, msg = DataGoKrSource._extract_result_code(data)
        assert code == "30"
        assert msg == "KEY_ERROR"

    def test_missing_header(self) -> None:
        """헤더가 없으면 기본값 99/UNKNOWN을 반환한다."""
        code, msg = DataGoKrSource._extract_result_code({})
        assert code == "99"
        assert msg == "UNKNOWN"


# ── _extract_items ───────────────────────────────────────────


class TestExtractItems:
    """응답 item 목록 추출 테스트."""

    def test_multiple_items(self) -> None:
        """여러 item을 추출한다."""
        items_data = [_make_item(srtn_cd="005930"), _make_item(srtn_cd="000660")]
        data = _make_response(items_data, total_count=2)
        items, total = DataGoKrSource._extract_items(data)
        assert len(items) == 2
        assert total == 2

    def test_single_item_as_dict(self) -> None:
        """단일 item이 dict로 올 경우 list로 감싼다."""
        single_item = _make_item()
        data = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "totalCount": 1,
                    "items": {"item": single_item},
                },
            }
        }
        items, total = DataGoKrSource._extract_items(data)
        assert len(items) == 1
        assert total == 1

    def test_empty_items(self) -> None:
        """items가 비어있으면 빈 리스트를 반환한다."""
        data = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "totalCount": 0,
                    "items": {},
                },
            }
        }
        items, total = DataGoKrSource._extract_items(data)
        assert items == []
        assert total == 0

    def test_no_body(self) -> None:
        """body가 없으면 빈 리스트를 반환한다."""
        data = {"response": {"header": {"resultCode": "00"}}}
        items, total = DataGoKrSource._extract_items(data)
        assert items == []
        assert total == 0


# ── _backoff_delay ───────────────────────────────────────────


class TestBackoffDelay:
    """Exponential Backoff + Full Jitter 테스트."""

    def test_attempt_0_bounded(self) -> None:
        """attempt=0일 때 0~1초 사이 값을 반환한다."""
        for _ in range(100):
            delay = DataGoKrSource._backoff_delay(0, base=1.0, cap=60.0)
            assert 0 <= delay <= 1.0

    def test_attempt_increases_bound(self) -> None:
        """attempt가 증가하면 상한이 증가한다."""
        # attempt=3 → max bound = min(60, 1*2^3) = 8.0
        for _ in range(100):
            delay = DataGoKrSource._backoff_delay(3, base=1.0, cap=60.0)
            assert 0 <= delay <= 8.0

    def test_cap_limits_delay(self) -> None:
        """cap 이상의 값을 반환하지 않는다."""
        for _ in range(100):
            delay = DataGoKrSource._backoff_delay(10, base=1.0, cap=5.0)
            assert 0 <= delay <= 5.0


# ── RateLimiter ──────────────────────────────────────────────


class TestRateLimiter:
    """RateLimiter 유닛 테스트."""

    def test_daily_count_starts_zero(self, rate_limiter: RateLimiter) -> None:
        """초기 일일 카운터는 0이다."""
        assert rate_limiter.daily_count == 0

    def test_increment_daily(self, rate_limiter: RateLimiter) -> None:
        """increment_daily는 카운터를 1 증가시킨다."""
        rate_limiter.increment_daily()
        assert rate_limiter.daily_count == 1

    def test_daily_limit_not_reached_initially(self, rate_limiter: RateLimiter) -> None:
        """초기 상태에서 한도에 도달하지 않았다."""
        assert not rate_limiter.is_daily_limit_reached()

    def test_daily_limit_reached_at_threshold(self) -> None:
        """90% 도달 시 True를 반환한다."""
        rl = RateLimiter(tps_limit=10.0, daily_limit=100)
        for _ in range(90):
            rl.increment_daily()
        assert rl.is_daily_limit_reached()

    def test_daily_limit_custom_threshold(self) -> None:
        """커스텀 threshold로 판별한다."""
        rl = RateLimiter(tps_limit=10.0, daily_limit=100)
        for _ in range(50):
            rl.increment_daily()
        assert rl.is_daily_limit_reached(threshold=0.5)
        assert not rl.is_daily_limit_reached(threshold=0.6)

    def test_reset_daily(self) -> None:
        """reset_daily는 카운터를 0으로 초기화한다."""
        rl = RateLimiter(tps_limit=10.0, daily_limit=100)
        for _ in range(50):
            rl.increment_daily()
        rl.reset_daily()
        assert rl.daily_count == 0

    @pytest.mark.asyncio
    async def test_acquire_decrements_tokens(self) -> None:
        """acquire는 토큰을 소비한다."""
        rl = RateLimiter(tps_limit=10.0, daily_limit=100)
        # 여러 번 acquire해도 에러 없이 동작한다
        for _ in range(5):
            await rl.acquire()

    def test_backward_compat_two_positional_args(self) -> None:
        """기존 호출부의 RateLimiter(tps, daily) 시그니처가 그대로 동작한다."""
        rl = RateLimiter(25.0, 10_000)
        assert rl.daily_count == 0
        rl.increment_daily()
        assert rl.daily_count == 1


# ── RateLimiter: token refill 시간 전진 (#2048) ───────────────


class TestRateLimiterTokenRefill:
    """#2048: sleep 경로의 _last_refill 전진으로 2x TPS 허용을 차단한다."""

    @pytest.mark.asyncio
    async def test_last_refill_advances_past_sleep(self) -> None:
        """토큰 소진 후 sleep 분기에서 _last_refill이 now + wait_time로 전진한다.

        sleep 동안 흐른 시간을 다음 acquire의 elapsed로 재크레딧하면 설정 TPS의
        약 2배가 허용된다. monotonic을 결정적으로 mock해 _last_refill이 sleep
        종료 시점으로 명시 전진하는지 단언한다.
        """
        rl = RateLimiter(tps_limit=2.0, daily_limit=100)
        # burst=2 토큰을 먼저 소진시키고, _last_refill을 mock 시계 기준으로 맞춘다.
        rl._tokens = 0.0
        rl._last_refill = 1000.0

        clock = {"t": 1000.0}
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            # 실제 이벤트 루프 시간 진행을 흉내내지 않아도 _last_refill 단언으로 충분.

        with (
            patch(
                "ante.feed.sources.base.time.monotonic",
                side_effect=lambda: clock["t"],
            ),
            patch(
                "ante.feed.sources.base.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            await rl.acquire()

        # rate=2 → 토큰 1개 충전에 wait_time = (1 - 0) / 2 = 0.5초.
        assert sleeps == [0.5]
        # _last_refill은 now(1000.0) + wait_time(0.5)로 전진해야 한다.
        assert rl._last_refill == pytest.approx(1000.5)
        # sleep 분기 종료 후 토큰은 0으로 유지된다.
        assert rl._tokens == 0.0

    @pytest.mark.asyncio
    async def test_throughput_not_exceed_configured_rate(self) -> None:
        """소진 후 연속 acquire의 누적 대기가 설정 rate를 초과 허용하지 않는다.

        _last_refill이 sleep만큼 전진하지 않으면 두 번째 sleep 분기가 첫
        sleep 구간을 재크레딧해 wait_time이 0으로 줄어든다(=2x TPS). 전진
        수정 후에는 acquire마다 1/rate초의 wait_time이 일정하게 유지된다.
        """
        rl = RateLimiter(tps_limit=2.0, daily_limit=100)
        # 토큰 소진 + _last_refill을 mock 시계 시작점으로 맞춘다.
        rl._tokens = 0.0
        rl._last_refill = 0.0

        clock = {"t": 0.0}
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            # sleep이 실제로 시계를 진행시킨다고 가정(상주 프로세스의 실시간).
            clock["t"] += seconds

        with (
            patch(
                "ante.feed.sources.base.time.monotonic",
                side_effect=lambda: clock["t"],
            ),
            patch(
                "ante.feed.sources.base.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            for _ in range(3):
                await rl.acquire()

        # rate=2 → 매 acquire마다 0.5초 대기가 일정하게 유지되어야 한다.
        # _last_refill이 전진하지 않으면 2번째 이후 wait_time이 0으로 붕괴된다.
        assert sleeps == [0.5, 0.5, 0.5]


# ── RateLimiter: 날짜 변경 self-reset (#2019) ─────────────────


class TestRateLimiterDailyReset:
    """#2019: 상주 프로세스가 자정을 넘겨도 daily_count가 self-reset된다."""

    def test_increment_resets_on_date_change(self) -> None:
        """D일 N회 증가 후 D+1로 바뀌면 다음 increment에서 1로 리셋된다."""
        current = {"d": date(2026, 6, 1)}
        rl = RateLimiter(tps_limit=10.0, daily_limit=100, now_date=lambda: current["d"])

        for _ in range(5):
            rl.increment_daily()
        assert rl.daily_count == 5

        current["d"] = date(2026, 6, 2)
        rl.increment_daily()
        assert rl.daily_count == 1

    def test_same_day_accumulates(self) -> None:
        """같은 날 내에서는 누적이 유지된다."""
        rl = RateLimiter(
            tps_limit=10.0, daily_limit=100, now_date=lambda: date(2026, 6, 1)
        )
        for _ in range(7):
            rl.increment_daily()
        assert rl.daily_count == 7

    def test_is_daily_limit_reached_resets_on_date_change(self) -> None:
        """증가 없이 자정을 넘긴 check도 새 날짜의 0을 반영해 한도 해제된다."""
        current = {"d": date(2026, 6, 1)}
        rl = RateLimiter(tps_limit=10.0, daily_limit=100, now_date=lambda: current["d"])

        for _ in range(90):
            rl.increment_daily()
        assert rl.is_daily_limit_reached() is True

        # 날짜가 바뀌면 increment 없이 check만으로도 카운터가 리셋된다.
        current["d"] = date(2026, 6, 2)
        assert rl.is_daily_limit_reached() is False
        assert rl.daily_count == 0

    def test_reset_daily_sets_current_date_baseline(self) -> None:
        """reset_daily는 카운터를 0으로 되돌리고 _daily_date를 현재로 갱신한다."""
        current = {"d": date(2026, 6, 1)}
        rl = RateLimiter(tps_limit=10.0, daily_limit=100, now_date=lambda: current["d"])

        for _ in range(10):
            rl.increment_daily()
        assert rl.daily_count == 10

        rl.reset_daily()
        assert rl.daily_count == 0
        assert rl._daily_date == date(2026, 6, 1)

        # reset 직후 같은 날 increment는 1부터 누적된다(재리셋 없음).
        rl.increment_daily()
        assert rl.daily_count == 1

    def test_default_now_date_uses_kst(self) -> None:
        """now_date 미지정 시 KST 기준 현재 날짜로 동작한다(스모크)."""
        from datetime import datetime

        from ante.feed.sources.base import _KST

        rl = RateLimiter(tps_limit=10.0, daily_limit=100)
        rl.increment_daily()
        assert rl.daily_count == 1
        assert rl._daily_date == datetime.now(tz=_KST).date()


# ── fetch_by_date ────────────────────────────────────────────


class TestFetchByDate:
    """fetch_by_date 통합 테스트 (mock HTTP)."""

    @pytest.mark.asyncio
    async def test_single_page(self, source: DataGoKrSource) -> None:
        """단일 페이지 응답을 정상 처리한다."""
        items = [_make_item(srtn_cd=f"00{i:04d}") for i in range(3)]
        response = _make_response(items, total_count=3)

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 3
        assert result[0]["srtnCd"] == "000000"

    @pytest.mark.asyncio
    async def test_pagination(self, source: DataGoKrSource) -> None:
        """여러 페이지를 순회하여 전체 데이터를 수집한다."""
        page1_items = [_make_item(srtn_cd=f"00{i:04d}") for i in range(1000)]
        page1 = _make_response(page1_items, total_count=1500)

        page2_items = [_make_item(srtn_cd=f"01{i:04d}") for i in range(500)]
        page2 = _make_response(page2_items, total_count=1500)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with patch.object(source, "_do_request", side_effect=mock_request):
            result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 1500
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_empty_date(self, source: DataGoKrSource) -> None:
        """데이터가 없는 날짜는 빈 리스트를 반환한다."""
        response = _make_response([], total_count=0)

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch_by_date("2024-01-01")

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_page_below_total_raises(self, source: DataGoKrSource) -> None:
        """빈 페이지인데 totalCount 미달이면 DataGoKrError를 발생시킨다 (#2069)."""
        page1 = _make_response([_make_item(srtn_cd="005930")], total_count=3)
        page2 = _make_response([], total_count=3)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with patch.object(source, "_do_request", side_effect=mock_request):
            with pytest.raises(DataGoKrError) as exc_info:
                await source.fetch_by_date("2024-03-01")

        # 부분 수집 메시지에 수집/전체 건수가 노출되어야 한다
        assert "collected=1" in str(exc_info.value)
        assert "total=3" in str(exc_info.value)
        # 빈 페이지(page2)까지 실제 호출되어야 한다
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_multi_page_exact_total_no_raise(
        self, source: DataGoKrSource
    ) -> None:
        """다중 페이지로 totalCount를 정확히 채우면 raise 없이 전건 반환한다."""
        page1_items = [_make_item(srtn_cd=f"00{i:04d}") for i in range(1000)]
        page1 = _make_response(page1_items, total_count=1001)
        page2_items = [_make_item(srtn_cd="019999")]
        page2 = _make_response(page2_items, total_count=1001)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with patch.object(source, "_do_request", side_effect=mock_request):
            result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 1001
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_single_page_exact_total_no_raise(
        self, source: DataGoKrSource
    ) -> None:
        """단일 페이지로 totalCount를 완수하면 정상 반환한다."""
        items = [_make_item(srtn_cd=f"00{i:04d}") for i in range(3)]
        response = _make_response(items, total_count=3)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            return response

        with patch.object(source, "_do_request", side_effect=mock_request):
            result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 3
        # totalCount 완수 시 추가 페이지 요청이 없어야 한다
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_daily_limit_raises(self, source: DataGoKrSource) -> None:
        """일일 한도 도달 시 DailyLimitExceededError를 발생시킨다."""
        # 한도의 90% 도달 상태 설정
        for _ in range(9000):
            source.rate_limiter.increment_daily()

        with pytest.raises(DailyLimitExceededError):
            await source.fetch_by_date("2024-03-01")

    @pytest.mark.asyncio
    async def test_critical_error_raises(self, source: DataGoKrSource) -> None:
        """서비스키 미등록 에러 시 CriticalApiError를 발생시킨다."""
        response = _make_response(
            [],
            result_code="30",
            result_msg="SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
        )

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(CriticalApiError):
                await source.fetch_by_date("2024-03-01")

    @pytest.mark.asyncio
    async def test_skip_error_raises(self, source: DataGoKrSource) -> None:
        """재시도 불가 에러 시 DataGoKrError를 발생시킨다."""
        response = _make_response(
            [],
            result_code="10",
            result_msg="INVALID_REQUEST_PARAMETER_ERROR",
        )

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(DataGoKrError):
                await source.fetch_by_date("2024-03-01")

    @pytest.mark.asyncio
    async def test_retry_then_success(self, source: DataGoKrSource) -> None:
        """재시도 가능 에러 후 성공하면 데이터를 반환한다."""
        error_response = _make_response(
            [],
            result_code="99",
            result_msg="UNKNOWN_ERROR",
        )
        success_response = _make_response([_make_item()], total_count=1)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_response
            return success_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self, source: DataGoKrSource) -> None:
        """재시도 소진 시 DataGoKrError를 발생시킨다."""
        error_response = _make_response(
            [],
            result_code="99",
            result_msg="UNKNOWN_ERROR",
        )

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=error_response
        ):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

    @pytest.mark.asyncio
    async def test_network_error_retries(self, source: DataGoKrSource) -> None:
        """네트워크 에러 시 재시도 후 성공하면 데이터를 반환한다."""
        import aiohttp

        success_response = _make_response([_make_item()], total_count=1)
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientConnectionError("Connection refused")
            return success_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                result = await source.fetch_by_date("2024-03-01")

        assert len(result) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_daily_limit_error_code_raises(self, source: DataGoKrSource) -> None:
        """API 에러 코드 22(일일 한도 초과) 시 DailyLimitExceededError를 발생시킨다."""
        response = _make_response(
            [],
            result_code="22",
            result_msg="LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
        )

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(DailyLimitExceededError):
                await source.fetch_by_date("2024-03-01")

    @pytest.mark.asyncio
    async def test_failed_attempts_counted_in_daily(
        self, source: DataGoKrSource
    ) -> None:
        """실패한 attempt도 daily_count에 반영된다 (#2106 repro).

        _do_request가 항상 ClientError를 던지면 max_retries(=2)번 시도하고
        최종 실패한다. 실제 HTTP 요청이 그만큼 나갔으므로 daily_count는
        attempt 수(=max_retries)와 같아야 한다. 기존엔 성공 후에만
        increment하여 0으로 남았다.
        """
        import aiohttp

        async def always_fail(session, params):
            raise aiohttp.ClientConnectionError("Connection refused")

        with patch.object(source, "_do_request", side_effect=always_fail):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        # max_retries=2 → 2번 시도, 모두 실패해도 2회 카운트
        assert source.rate_limiter.daily_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_success_counts_once_no_double(self, source: DataGoKrSource) -> None:
        """성공 시 attempt 1회만 카운트되고 이중 카운트가 없다 (#2106).

        단일 페이지 성공 → daily_count == 1.
        """
        response = _make_response([_make_item()], total_count=1)

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            await source.fetch_by_date("2024-03-01")

        assert source.rate_limiter.daily_count == 1

    @pytest.mark.asyncio
    async def test_multi_page_count_equals_page_count(
        self, source: DataGoKrSource
    ) -> None:
        """다중 페이지 수집 시 daily_count == page 수 (이중 카운트 없음, #2106)."""
        page1_items = [_make_item(srtn_cd=f"00{i:04d}") for i in range(1000)]
        page1 = _make_response(page1_items, total_count=1500)
        page2_items = [_make_item(srtn_cd=f"01{i:04d}") for i in range(500)]
        page2 = _make_response(page2_items, total_count=1500)

        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            return page1 if call_count == 1 else page2

        with patch.object(source, "_do_request", side_effect=mock_request):
            await source.fetch_by_date("2024-03-01")

        # 2 페이지 = 2 attempt = 2 increment
        assert call_count == 2
        assert source.rate_limiter.daily_count == 2

    @pytest.mark.asyncio
    async def test_retry_then_success_counts_each_attempt(
        self, source: DataGoKrSource
    ) -> None:
        """재시도 후 성공 시 실패 attempt + 성공 attempt 모두 카운트된다 (#2106).

        첫 시도(ClientError 실패) + 두 번째 시도(성공) → daily_count == 2.
        실제 HTTP 요청이 2회 나갔으므로 2회 카운트가 맞다.
        """
        import aiohttp

        success_response = _make_response([_make_item()], total_count=1)
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientConnectionError("Connection refused")
            return success_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                await source.fetch_by_date("2024-03-01")

        assert call_count == 2
        assert source.rate_limiter.daily_count == 2

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_fetch_by_date(
        self, source: DataGoKrSource
    ) -> None:
        """fetch()는 fetch_by_date()에 위임한다."""
        response = _make_response([_make_item()], total_count=1)

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch("2024-03-01")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_date_format_conversion(self, source: DataGoKrSource) -> None:
        """YYYY-MM-DD 형식을 YYYYMMDD로 변환하여 요청한다."""
        response = _make_response([_make_item()], total_count=1)
        captured_params: list[dict] = []

        async def mock_request(session, params):
            captured_params.append(params)
            return response

        with patch.object(source, "_do_request", side_effect=mock_request):
            await source.fetch_by_date("2024-03-01")

        assert captured_params[0]["basDt"] == "20240301"


# ── HTTP status 재시도 분류 (#2026) ───────────────────────────


def _client_response_error(status: int) -> aiohttp.ClientResponseError:
    """지정 status를 가진 aiohttp.ClientResponseError를 생성한다."""
    request_info = aiohttp.RequestInfo(
        url=URL("https://apis.data.go.kr/test"),
        method="GET",
        headers=CIMultiDict(),
        real_url=URL("https://apis.data.go.kr/test"),
    )
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=f"HTTP {status}",
    )


class TestHttpStatusRetryPolicy:
    """#2026: HTTP 4xx 비재시도 / 408·429·5xx·timeout·연결 오류 재시도."""

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    @pytest.mark.asyncio
    async def test_non_retryable_status_fails_immediately(
        self, source: DataGoKrSource, status: int
    ) -> None:
        """400/401/403/404/422는 재시도 없이 1회 호출 후 즉시 실패한다."""
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            raise _client_response_error(status)

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError):
                    await source.fetch_by_date("2024-03-01")

        # 재시도 0 → _do_request 정확히 1회 호출
        assert call_count == 1

    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
    @pytest.mark.asyncio
    async def test_retryable_status_retries(
        self, source: DataGoKrSource, status: int
    ) -> None:
        """408/429/5xx ClientResponseError는 max_retries까지 재시도한다."""
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            raise _client_response_error(status)

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        # max_retries(=2)만큼 호출
        assert call_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_timeout_error_retries(self, source: DataGoKrSource) -> None:
        """TimeoutError는 재시도 대상이다."""
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timed out")

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        assert call_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_connection_error_without_status_retries(
        self, source: DataGoKrSource
    ) -> None:
        """status 없는 ClientConnectionError(연결 오류)는 재시도 대상이다."""
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            raise aiohttp.ClientConnectionError("Connection refused")

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        assert call_count == source._max_retries == 2


# ── UNKNOWN(99) RETRY_ONCE 1회 재시도 cap (#2027) ─────────────


class TestRetryOnceCap:
    """#2027: resultCode=99(UNKNOWN)는 1회만 재시도(총 2회 호출) 후 스킵."""

    @pytest.mark.asyncio
    async def test_unknown_code_retries_once_then_skips(
        self, rate_limiter: RateLimiter
    ) -> None:
        """99는 max_retries(=3)와 무관하게 2회 호출(1회 재시도) 후 실패한다."""
        # cap이 max_retries보다 작게 동작함을 보이려고 max_retries=3으로 둔다.
        source = DataGoKrSource(
            api_key="test-api-key", rate_limiter=rate_limiter, max_retries=3
        )
        error_response = _make_response(
            [], result_code="99", result_msg="UNKNOWN_ERROR"
        )
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            return error_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        # RETRY_ONCE → 최초 1회 + 재시도 1회 = 총 2회 (max_retries=3 미사용)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_general_retry_code_uses_max_retries(
        self, rate_limiter: RateLimiter
    ) -> None:
        """일반 RETRY 코드(01)는 max_retries(=3) 전체를 사용한다 (회귀)."""
        source = DataGoKrSource(
            api_key="test-api-key", rate_limiter=rate_limiter, max_retries=3
        )
        error_response = _make_response(
            [], result_code="01", result_msg="APPLICATION_ERROR"
        )
        call_count = 0

        async def mock_request(session, params):
            nonlocal call_count
            call_count += 1
            return error_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DataGoKrError, match="최종 실패"):
                    await source.fetch_by_date("2024-03-01")

        # 일반 RETRY → max_retries(=3)회 호출
        assert call_count == 3


# ── DataGoKrCollector: srtnCd KRX 검증 (#2080) ────────────────


def _raw(srtn: object) -> dict:
    """data.go.kr raw item(이슈 재현 dict, normalizer 기대 필드 셋)."""
    return {
        "basDt": "20260102",
        "srtnCd": srtn,
        "mkp": "100",
        "hipr": "110",
        "lopr": "90",
        "clpr": "105",
        "trqu": "1000",
        "trPrc": "100000",
        "mrktTotAmt": "1000000",
        "lstgStCnt": "10000",
    }


class _FakeSource:
    """fetch(date)가 미리 지정한 raw item 리스트를 반환하는 가짜 source."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    async def fetch(self, target_date: str) -> list[dict]:
        return self._items


def _invalid_symbol_warns(warns: list[dict]) -> list[dict]:
    """warns 목록에서 invalid_symbol 타입만 추출한다."""
    return [w for w in warns if w.get("type") == "invalid_symbol"]


class TestCollectorSymbolValidation:
    """DataGoKrCollector가 비KRX srtnCd를 drop+warning 처리한다 (#2080)."""

    @pytest.mark.asyncio
    async def test_non_krx_symbol_dropped(self, tmp_path) -> None:
        """(a) srtnCd='ABCDEF' 단일 → 저장 0, invalid_symbol warning 1건."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("ABCDEF")]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        invalid = _invalid_symbol_warns(warns)
        assert len(invalid) == 1
        assert "ABCDEF" in invalid[0]["message"]
        assert store.list_symbols("1d") == []
        assert store.list_symbols(data_type="fundamental") == []

    @pytest.mark.asyncio
    async def test_valid_krx_symbol_stored(self, tmp_path) -> None:
        """(b) 정상 KRX '005930' → 저장됨, invalid_symbol warning 없음."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        assert _invalid_symbol_warns(warns) == []
        assert store.list_symbols("1d") == ["005930"]
        assert store.list_symbols(data_type="fundamental") == ["005930"]

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, tmp_path) -> None:
        """(c) 혼합('005930'+'ABCDEF') → valid만 저장, invalid drop+warning."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw("005930"), _raw("ABCDEF")])
        )

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        invalid = _invalid_symbol_warns(warns)
        assert len(invalid) == 1
        assert "ABCDEF" in invalid[0]["message"]
        assert store.list_symbols("1d") == ["005930"]
        assert store.list_symbols(data_type="fundamental") == ["005930"]

    @pytest.mark.asyncio
    async def test_non_string_symbols_dropped(self, tmp_path) -> None:
        """(d) 비문자열/None srtnCd(None, 123456 int) → drop+warning."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw(None), _raw(123456)]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        assert len(_invalid_symbol_warns(warns)) == 2
        assert store.list_symbols("1d") == []
        assert store.list_symbols(data_type="fundamental") == []

    @pytest.mark.asyncio
    async def test_unicode_digit_symbol_dropped(self, tmp_path) -> None:
        """(e) Unicode digit '１２３４５６' → drop(ASCII 아님)."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("１２３４５６")]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        assert len(_invalid_symbol_warns(warns)) == 1
        assert store.list_symbols("1d") == []
        assert store.list_symbols(data_type="fundamental") == []


# ── DataGoKrCollector: raw schema 검증 (#2055 / #2008) ─────────


def _schema_warns(warns: list[dict]) -> list[dict]:
    """warns 목록에서 schema_validation 타입만 추출한다."""
    return [w for w in warns if w.get("type") == "schema_validation"]


class TestCollectorSchemaValidation:
    """DataGoKrCollector가 raw 스키마 실패 레코드를 skip하고 surface한다 (#2055)."""

    @pytest.mark.asyncio
    async def test_valid_raw_no_false_schema_failure(self, tmp_path) -> None:
        """정상 raw → 허위 schema 실패 0건, 정규화/저장 정상(rows>0)."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        assert _schema_warns(warns) == []
        assert store.list_symbols("1d") == ["005930"]

    @pytest.mark.asyncio
    async def test_missing_required_field_skipped(self, tmp_path) -> None:
        """raw 필수 필드(mkp) 누락 레코드 → skip + schema_validation warning."""
        store = ParquetStore(base_path=tmp_path)
        item = _raw("005930")
        del item["mkp"]
        collector = DataGoKrCollector(source=_FakeSource([item]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        schema = _schema_warns(warns)
        assert len(schema) == 1
        assert "mkp" in schema[0]["message"]
        assert store.list_symbols("1d") == []

    @pytest.mark.asyncio
    async def test_null_required_field_skipped(self, tmp_path) -> None:
        """raw 필수 필드(clpr) null 레코드 → missing과 동일하게 skip."""
        store = ParquetStore(base_path=tmp_path)
        item = _raw("005930")
        item["clpr"] = None
        collector = DataGoKrCollector(source=_FakeSource([item]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        schema = _schema_warns(warns)
        assert len(schema) == 1
        assert "clpr" in schema[0]["message"]
        assert store.list_symbols("1d") == []

    @pytest.mark.asyncio
    async def test_mixed_valid_and_malformed(self, tmp_path) -> None:
        """혼합 batch(valid + malformed) → valid만 저장, malformed surface."""
        store = ParquetStore(base_path=tmp_path)
        good = _raw("005930")
        bad_missing = _raw("000660")
        del bad_missing["hipr"]
        bad_null = _raw("035720")
        bad_null["trqu"] = None
        collector = DataGoKrCollector(source=_FakeSource([good, bad_missing, bad_null]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        assert len(_schema_warns(warns)) == 2
        assert store.list_symbols("1d") == ["005930"]

    @pytest.mark.asyncio
    async def test_business_anomaly_record_kept(self, tmp_path) -> None:
        """business 이상치(lopr>hipr)도 schema는 통과하므로 survivor 저장 유지(회귀).

        business 계층은 비차단(경고)이므로 schema를 통과한 레코드는 값 이상치가
        있어도 저장된다. raw 키(lopr/hipr)는 business 계층이 보는 정규화 컬럼명
        (low/high)이 아니어서 collect 단계의 raw warns에는 잡히지 않지만,
        핵심 회귀 불변은 'schema 통과 → 차단되지 않고 저장'이다.
        """
        store = ParquetStore(base_path=tmp_path)
        # lopr(=200) > hipr(=110): 값 이상치이지만 raw 필수 필드는 모두 존재.
        item = _raw("005930")
        item["lopr"] = "200"
        collector = DataGoKrCollector(source=_FakeSource([item]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        assert _schema_warns(warns) == []
        assert store.list_symbols("1d") == ["005930"]

    def test_business_layer_warns_on_normalized_keys(self) -> None:
        """business 계층은 정규화 컬럼명(low/high) 기준으로 warning을 낸다(회귀).

        survivor 검증이 business_rule 채널을 보존하는지 직접 확인한다.
        """
        from ante.feed.transform.validate import validate_all

        norm = {
            "timestamp": "20260102",
            "symbol": "005930",
            "open": 100.0,
            "high": 110.0,
            "low": 200.0,  # low > high/open/close → business 위반
            "close": 105.0,
            "volume": 1000,
        }
        result = validate_all(
            [norm],
            ["timestamp", "symbol", "open", "high", "low", "close", "volume"],
        )
        assert result.passed is True  # business 위반은 차단하지 않음
        assert result.errors == []
        assert any("low > " in w for w in result.warnings)

    def test_validate_all_passes_for_valid_raw(self) -> None:
        """#2055/#2008 repro: 정상 raw가 도출 상수로 schema PASS."""
        from ante.data.normalizer import DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS
        from ante.feed.transform.validate import validate_all

        result = validate_all(
            [_raw("005930")], list(DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS)
        )
        assert result.passed is True
        assert result.errors == []


# ── DataGoKrCollector: validate_all 실패 게이트 (#2055 Codex FAIL) ──


class _RecordingStore:
    """write() 호출을 기록하는 가짜 store (저장 차단 검증용).

    write()는 ParquetStore와 동형으로 **net-new 저장 행 수**(int)를 반환한다
    (#1993 fake store sweep). 신규 write로 가정해 ``len(df)`` 를 반환하므로,
    collector의 ``rows += store.write(...)`` 누적이 None으로 깨지지 않는다.
    """

    def __init__(self) -> None:
        self.writes: list[tuple] = []

    def write(self, symbol, timeframe, df, data_type) -> int:
        self.writes.append((symbol, timeframe, data_type, len(df)))
        return len(df)


class TestCollectorValidationGate:
    """survivor batch가 validate_all에서 passed=False면 저장을 차단한다 (#2055).

    선필터(missing/null per-record skip)가 못 잡는 잔여 실패(transport
    status≠200, syntax, 또는 향후 schema 검사)는 비차단으로 남으면 안 된다.
    spec(09-failure-recovery.md): schema 실패 레코드는 skip(저장 금지).
    """

    @pytest.mark.asyncio
    async def test_validate_all_failure_blocks_store(self, monkeypatch, caplog) -> None:
        """validate_all이 passed=False → survivor 저장 차단(write 미호출, rows=0).

        warns에 schema_validation 엔트리가 surface되고 logger.error가 남는다.
        선필터(missing/null)로는 잡히지 않는 정상 raw survivor를 쓰지만,
        validate_all을 직접 monkeypatch하여 transport/syntax 잔여 실패를 모사한다.
        """
        import logging

        from ante.feed.models.result import ValidationResult

        store = _RecordingStore()
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        def _fake_validate_all(records, required_fields, status_code=200):
            # transport status≠200 잔여 실패를 모사: passed=False + errors.
            return ValidationResult(
                passed=False,
                warnings=[],
                errors=["HTTP 상태 코드 오류: 503"],
            )

        monkeypatch.setattr(
            "ante.feed.pipeline.data_go_kr_collector.validate_all",
            _fake_validate_all,
        )

        with caplog.at_level(logging.ERROR):
            rows, _stored_ok, symbols, warns = await collector.collect(
                "20260102", store
            )

        # 저장 차단: write 미호출, rows_written=0, symbols 추가 0.
        assert rows == 0
        assert symbols == set()
        assert store.writes == []
        # schema_validation 엔트리 surface.
        schema = _schema_warns(warns)
        assert len(schema) == 1
        assert "503" in schema[0]["message"]
        # logger.error 남김.
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    @pytest.mark.asyncio
    async def test_validate_all_failure_does_not_raise(self, monkeypatch) -> None:
        """passed=False여도 예외 없이 (0, False, set(), warns)로 정상 반환한다.

        다른 날짜/소스 수집을 막지 않도록 부분 결과를 정상 반환해야 한다.
        collect() (net_delta, stored_ok, syms, warns) 4-tuple 시그니처(#1993).
        validation 차단은 stored_ok=False다.
        """
        from ante.feed.models.result import ValidationResult

        store = _RecordingStore()
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        monkeypatch.setattr(
            "ante.feed.pipeline.data_go_kr_collector.validate_all",
            lambda records, required_fields, status_code=200: ValidationResult(
                passed=False, warnings=[], errors=["JSON 파싱 오류: mock"]
            ),
        )

        result = await collector.collect("20260102", store)

        assert isinstance(result, tuple)
        assert len(result) == 4
        net_delta, stored_ok, syms, warns = result
        assert net_delta == 0
        assert stored_ok is False
        assert syms == set()
        assert isinstance(warns, list)

    @pytest.mark.asyncio
    async def test_all_records_prefiltered_empty_survivors(self, tmp_path) -> None:
        """선필터로 모든 레코드가 drop되어 survivors=[] → 저장 0건, 크래시/에러 없음.

        validate_all([])은 빈-레코드 schema로 passed=True지만, survivors가
        비어있으면 게이트 이전에 조기 반환하여 0건 저장으로 정상 통과한다.
        """
        store = ParquetStore(base_path=tmp_path)
        # 두 레코드 모두 필수 필드 누락 → 선필터가 전부 drop.
        bad1 = _raw("005930")
        del bad1["mkp"]
        bad2 = _raw("000660")
        del bad2["clpr"]
        collector = DataGoKrCollector(source=_FakeSource([bad1, bad2]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        # 두 레코드 모두 schema 선필터 skip warning으로 surface.
        assert len(_schema_warns(warns)) == 2
        assert store.list_symbols("1d") == []
        assert store.list_symbols(data_type="fundamental") == []


# ── DataGoKrCollector: instruments.parquet 갱신 (#2020) ────────


def _raw_inst(
    srtn: str = "005930",
    itms_nm: str | None = "삼성전자",
    mrkt_ctg: str | None = "KOSPI",
) -> dict:
    """instruments 메타데이터 필드(itmsNm/mrktCtg)를 포함한 raw item.

    itms_nm/mrkt_ctg를 None으로 주면 해당 키를 제거한다(컬럼 누락 모사).
    """
    item = _raw(srtn)
    if itms_nm is not None:
        item["itmsNm"] = itms_nm
    if mrkt_ctg is not None:
        item["mrktCtg"] = mrkt_ctg
    return item


def _read_instruments(store: ParquetStore):
    """`.feed/instruments.parquet`를 읽어 (path, DataFrame) 반환.

    없으면 (path, None).
    """
    import polars as pl

    path = store.base_path / ".feed" / "instruments.parquet"
    if not path.exists():
        return path, None
    return path, pl.read_parquet(path)


class TestCollectorInstrumentsStore:
    """#2020: data.go.kr 수집 시 .feed/instruments.parquet upsert."""

    @pytest.mark.asyncio
    async def test_instruments_written_on_collect(self, tmp_path) -> None:
        """(a) collect → instruments.parquet 생성.

        symbol/exchange/name/market 채워짐.
        """
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", "KOSPI")])
        )

        await collector.collect("20260102", store)

        path, df = _read_instruments(store)
        assert path == tmp_path / ".feed" / "instruments.parquet"
        assert df is not None
        assert df.columns == ["symbol", "exchange", "name", "market"]
        row = df.filter(df["symbol"] == "005930").to_dicts()[0]
        assert row == {
            "symbol": "005930",
            "exchange": "KRX",
            "name": "삼성전자",
            "market": "KOSPI",
        }

    @pytest.mark.asyncio
    async def test_instruments_upsert_no_duplicate_across_days(self, tmp_path) -> None:
        """(b) 같은 심볼 2일 수집 → symbol upsert, 중복 0행."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", "KOSPI")])
        )

        await collector.collect("20260102", store)
        await collector.collect("20260103", store)

        _, df = _read_instruments(store)
        assert df is not None
        assert df.height == 1
        assert df["symbol"].to_list() == ["005930"]

    @pytest.mark.asyncio
    async def test_instruments_empty_new_values_preserve_existing(
        self, tmp_path
    ) -> None:
        """(c) 신규 row의 itmsNm/mrktCtg 빈값 → 기존 non-empty 보존(덮어쓰기 안 함)."""
        store = ParquetStore(base_path=tmp_path)
        # 1일차: name/market 채워서 저장.
        first = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", "KOSPI")])
        )
        await first.collect("20260102", store)

        # 2일차: itmsNm/mrktCtg 키 자체가 없는(누락) raw → 빈 값으로 들어옴.
        second = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", itms_nm=None, mrkt_ctg=None)])
        )
        await second.collect("20260103", store)

        _, df = _read_instruments(store)
        assert df is not None
        assert df.height == 1
        row = df.filter(df["symbol"] == "005930").to_dicts()[0]
        # 빈 신규값이 기존 non-empty를 덮어쓰지 않아야 한다.
        assert row["name"] == "삼성전자"
        assert row["market"] == "KOSPI"

    @pytest.mark.asyncio
    async def test_instruments_non_empty_new_values_update(self, tmp_path) -> None:
        """신규 non-empty 값은 기존 값을 갱신한다."""
        store = ParquetStore(base_path=tmp_path)
        first = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "구종목명", "KOSPI")])
        )
        await first.collect("20260102", store)

        second = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", "KOSDAQ")])
        )
        await second.collect("20260103", store)

        _, df = _read_instruments(store)
        assert df is not None
        row = df.filter(df["symbol"] == "005930").to_dicts()[0]
        assert row["name"] == "삼성전자"
        assert row["market"] == "KOSDAQ"

    @pytest.mark.asyncio
    async def test_instruments_multiple_symbols(self, tmp_path) -> None:
        """여러 심볼 수집 → 각 심볼 1행씩 instruments에 기록."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource(
                [
                    _raw_inst("005930", "삼성전자", "KOSPI"),
                    _raw_inst("000660", "SK하이닉스", "KOSPI"),
                    _raw_inst("035720", "카카오", "KOSDAQ"),
                ]
            )
        )

        await collector.collect("20260102", store)

        _, df = _read_instruments(store)
        assert df is not None
        assert df.height == 3
        assert set(df["symbol"].to_list()) == {"005930", "000660", "035720"}

    @pytest.mark.asyncio
    async def test_ohlcv_fundamental_no_regression_with_instruments(
        self, tmp_path
    ) -> None:
        """(d) instruments 저장 추가 후에도 ohlcv/fundamental 저장이 회귀 없이 유지."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", "KOSPI")])
        )

        rows, _stored_ok, symbols, _ = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        assert store.list_symbols("1d") == ["005930"]
        assert store.list_symbols(data_type="fundamental") == ["005930"]
        # instruments도 함께 기록된다.
        _, df = _read_instruments(store)
        assert df is not None
        assert df["symbol"].to_list() == ["005930"]

    @pytest.mark.asyncio
    async def test_instruments_not_written_on_missing_meta_columns(
        self, tmp_path
    ) -> None:
        """(e) itmsNm/mrktCtg 컬럼 둘 다 전무 → 무가치 파일 미생성(크래시 없음).

        메타데이터가 전혀 없으면(srtnCd만 존재) instruments.parquet를 생성하지
        않는다. ohlcv/fundamental 등 다른 저장 경로는 정상 진행한다.
        """
        store = ParquetStore(base_path=tmp_path)
        # itmsNm/mrktCtg 키가 전혀 없는 raw(=_raw 기본).
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        rows, _stored_ok, symbols, _ = await collector.collect("20260102", store)

        assert rows > 0
        assert symbols == {"005930"}
        path, df = _read_instruments(store)
        assert not path.exists()
        assert df is None

    @pytest.mark.asyncio
    async def test_instruments_written_with_only_name_column(self, tmp_path) -> None:
        """메타 컬럼이 하나만 있어도(itmsNm만) 파일 생성, 누락 컬럼은 빈 문자열."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", "삼성전자", mrkt_ctg=None)])
        )

        await collector.collect("20260102", store)

        path, df = _read_instruments(store)
        assert path.exists()
        assert df is not None
        row = df.filter(df["symbol"] == "005930").to_dicts()[0]
        assert row["name"] == "삼성전자"
        assert row["market"] == ""

    @pytest.mark.asyncio
    async def test_instruments_written_with_only_market_column(self, tmp_path) -> None:
        """메타 컬럼이 하나만 있어도(mrktCtg만) 파일 생성, 누락 컬럼은 빈 문자열."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw_inst("005930", itms_nm=None, mrkt_ctg="KOSPI")])
        )

        await collector.collect("20260102", store)

        path, df = _read_instruments(store)
        assert path.exists()
        assert df is not None
        row = df.filter(df["symbol"] == "005930").to_dicts()[0]
        assert row["name"] == ""
        assert row["market"] == "KOSPI"

    @pytest.mark.asyncio
    async def test_instruments_not_written_on_empty_response(self, tmp_path) -> None:
        """(e) 빈 응답 → instruments 파일 미생성, 크래시 없음."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([]))

        rows, _stored_ok, symbols, warns = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        path, df = _read_instruments(store)
        assert not path.exists()
        assert df is None

    @pytest.mark.asyncio
    async def test_instruments_not_written_on_all_dropped(self, tmp_path) -> None:
        """모든 레코드가 선필터 drop되어 survivors=[] → instruments 미생성."""
        store = ParquetStore(base_path=tmp_path)
        bad = _raw_inst("005930", "삼성전자", "KOSPI")
        del bad["mkp"]  # 필수 필드 누락 → 선필터 drop.
        collector = DataGoKrCollector(source=_FakeSource([bad]))

        rows, _stored_ok, symbols, _ = await collector.collect("20260102", store)

        assert rows == 0
        assert symbols == set()
        path, df = _read_instruments(store)
        assert not path.exists()
        assert df is None


# ── validate_credentials (#2046) ──────────────────────────────


class TestValidateCredentials:
    """data.go.kr 서비스키 유효성 3-state 검증 (mock HTTP, 실 네트워크 없음)."""

    @pytest.mark.asyncio
    async def test_valid_key_ok(self, source: DataGoKrSource) -> None:
        """정상 응답(00) → valid=True."""
        response = _make_response([_make_item()], total_count=1)
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, detail = await source.validate_credentials()
        assert valid is True
        assert detail is None

    @pytest.mark.asyncio
    async def test_invalid_key_30(self, source: DataGoKrSource) -> None:
        """서비스키 미등록(30) → valid=False, 사유 포함."""
        response = _make_response(
            [],
            total_count=0,
            result_code="30",
            result_msg="SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
        )
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, detail = await source.validate_credentials()
        assert valid is False
        assert detail is not None
        assert "30" in detail

    @pytest.mark.asyncio
    async def test_invalid_key_31_expired(self, source: DataGoKrSource) -> None:
        """기한 만료(31)도 인증 실패 → valid=False."""
        response = _make_response(
            [],
            total_count=0,
            result_code="31",
            result_msg="DEADLINE_HAS_EXPIRED_ERROR",
        )
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, _ = await source.validate_credentials()
        assert valid is False

    @pytest.mark.asyncio
    async def test_network_error_unknown(self, source: DataGoKrSource) -> None:
        """네트워크 예외 → valid=None(검증 불가), 예외 미전파."""
        with patch.object(
            source,
            "_do_request",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("connection refused"),
        ):
            valid, detail = await source.validate_credentials()
        assert valid is None
        assert detail is not None
        assert "네트워크" in detail

    @pytest.mark.asyncio
    async def test_timeout_unknown(self, source: DataGoKrSource) -> None:
        """타임아웃 → valid=None(검증 불가), 예외 미전파."""

        async def _slow(*args: object, **kwargs: object) -> dict:
            raise TimeoutError

        with patch.object(source, "_do_request", side_effect=_slow):
            valid, detail = await source.validate_credentials()
        assert valid is None
        assert detail is not None


# ── DataGoKrCollector: stored_ok = bool(symbols) 유도 (#1993 Finding 1) ─────


class _EmptyNormalizer:
    """normalize_ohlcv·normalize_fundamental이 둘 다 **빈** DataFrame을 반환한다.

    survivor가 validation을 통과해도(정상 raw) 정규화 단계에서 추가 drop돼
    저장 0건이 되는 케이스를 모사한다(no-symbol). DataGoKrNormalizer와 동형
    시그니처를 제공한다(collector가 normalize_ohlcv/normalize_fundamental만
    호출하므로 그 둘만 정의).
    """

    def normalize_ohlcv(self, df):  # type: ignore[no-untyped-def]
        import polars as pl

        return pl.DataFrame()

    def normalize_fundamental(self, df):  # type: ignore[no-untyped-def]
        import polars as pl

        return pl.DataFrame()


class TestCollectorStoredOkFromSymbols:
    """stored_ok가 하드코딩 True가 아니라 bool(symbols)에서 유도된다 (#1993 Finding 1).

    survivor가 validation을 통과해도 정규화 단계에서 ohlcv·fundamental이 둘 다
    no-symbol이면 실제 저장 0건이다. 이때 stored_ok=True로 하드코딩하면 저장이
    없는데 checkpoint가 전진해 데이터가 영구 skip된다(회귀). bool(symbols)로
    유도하면 둘 다 빈 정규화 결과는 stored_ok=False(미전진)로 가드된다.
    """

    @pytest.mark.asyncio
    async def test_normalize_all_drop_yields_stored_ok_false(self, tmp_path) -> None:
        """정규화 단계 전drop(둘 다 no-symbol) → stored_ok=False, symbols 빈 set."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(
            source=_FakeSource([_raw("005930")]),
            normalizer=_EmptyNormalizer(),  # type: ignore[arg-type]
        )

        net_delta, stored_ok, symbols, _warns = await collector.collect(
            "20260102", store
        )

        # 정규화 결과 0심볼 → 저장 0건 → bool(symbols)=False.
        assert net_delta == 0
        assert symbols == set()
        assert stored_ok is False
        # 실제로 어떤 데이터도 저장되지 않았다.
        assert store.list_symbols("1d") == []
        assert store.list_symbols(data_type="fundamental") == []

    @pytest.mark.asyncio
    async def test_normal_data_yields_stored_ok_true(self, tmp_path) -> None:
        """정상 데이터(기본 normalizer) → stored_ok=True(회귀 가드)."""
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        net_delta, stored_ok, symbols, _warns = await collector.collect(
            "20260102", store
        )

        assert net_delta > 0
        assert symbols == {"005930"}
        assert stored_ok is True

    @pytest.mark.asyncio
    async def test_recollect_delta_zero_yields_stored_ok_true(self, tmp_path) -> None:
        """재수집(net_delta=0, 정규화 정상) → stored_ok=True(전진 유지, 회귀 가드).

        같은 날짜를 두 번 collect한다. 2차는 dedup으로 net_delta=0이지만 정규화는
        정상이라 symbols가 비어있지 않아 stored_ok=True여야 한다(stall 방지).
        """
        store = ParquetStore(base_path=tmp_path)
        collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

        await collector.collect("20260102", store)
        net_delta2, stored_ok2, symbols2, _warns2 = await collector.collect(
            "20260102", store
        )

        # 재수집 → net-new 0이지만 정규화/저장 호출은 정상 → stored_ok True.
        assert net_delta2 == 0
        assert symbols2 == {"005930"}
        assert stored_ok2 is True


class _StoredOkScriptedCollector:
    """runner 통합용: collect가 collector 단위 결과를 그대로 전달하는 thin wrapper.

    실 DataGoKrCollector를 감싸 _collect_data_go_kr가 collector의 stored_ok를
    그대로 받아 checkpoint를 게이트하는지 잠근다(#1993 Finding 1 end-to-end).
    """

    def __init__(self, inner: DataGoKrCollector) -> None:
        self._inner = inner
        self.calls: list[str] = []

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, bool, set[str], list[dict]]:
        self.calls.append(target_date)
        return await self._inner.collect(target_date, store)


class TestCollectorStoredOkRunnerGate:
    """runner가 collector stored_ok=False(정규화 전drop) 날짜를 미전진시킨다."""

    @pytest.mark.asyncio
    async def test_runner_blocks_checkpoint_on_normalize_all_drop(
        self, tmp_path
    ) -> None:
        """정규화 전drop 날짜(stored_ok=False) → 해당 날짜 checkpoint 미전진.

        Finding 1 회귀: collector가 저장 0건인데 stored_ok=True를 하드코딩하면
        runner가 checkpoint를 전진시켜 데이터 영구 skip. bool(symbols) 유도로
        stored_ok=False가 되어 runner의 기존 stored_ok 가드가 미전진시킨다.
        """
        from ante.feed.pipeline.backfill_runner import BackfillRunner, _RunContext
        from ante.feed.pipeline.checkpoint import Checkpoint

        feed_dir = tmp_path / ".feed"
        store = ParquetStore(base_path=tmp_path / "data")
        inner = DataGoKrCollector(
            source=_FakeSource([_raw("005930")]),
            normalizer=_EmptyNormalizer(),  # type: ignore[arg-type]
        )
        collector = _StoredOkScriptedCollector(inner)
        checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        runner = BackfillRunner(data_go_kr_collector=collector)
        ctx = _RunContext()

        await runner._collect_data_go_kr(
            ["2026-01-02"],
            {},
            store,
            checkpoint,
            ctx,
            lambda _config, _date: False,
            lambda _config: False,
            None,
        )

        # 정규화 전drop으로 stored_ok=False → checkpoint 미전진(영구 skip 방지).
        assert checkpoint.get_last_date() is None
        assert collector.calls == ["2026-01-02"]
