"""data.go.kr 소스 어댑터 유닛 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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
        """99는 RETRY로 분류한다."""
        assert classify_error("99") == ErrorAction.RETRY

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
