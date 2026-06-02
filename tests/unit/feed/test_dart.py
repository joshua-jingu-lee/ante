"""DART 소스 어댑터 유닛 테스트."""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import AsyncMock, patch
from xml.etree.ElementTree import Element, SubElement, tostring

import aiohttp
import pytest
from multidict import CIMultiDict
from yarl import URL

from ante.feed.sources.base import RateLimiter
from ante.feed.sources.dart import (
    CriticalApiError,
    DailyLimitExceededError,
    DARTError,
    DARTSource,
    ErrorAction,
    classify_error,
)

# -- 테스트 헬퍼 --------------------------------------------------------


def _make_corp_code_zip(entries: list[dict[str, str]]) -> bytes:
    """corp_code ZIP 파일 바이트를 생성한다.

    Args:
        entries: [{"corp_code": "...", "corp_name": "...", "stock_code": "..."}, ...]
    """
    root = Element("result")
    for entry in entries:
        item = SubElement(root, "list")
        for key, value in entry.items():
            child = SubElement(item, key)
            child.text = value

    xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CORPCODE.xml", xml_bytes)
    return buf.getvalue()


def _make_financial_response(
    items: list[dict],
    status: str = "000",
    message: str = "정상",
) -> dict:
    """DART fnlttMultiAcnt mock 응답을 생성한다."""
    return {
        "status": status,
        "message": message,
        "list": items,
    }


def _make_financial_item(
    corp_code: str = "00126380",
    stock_code: str = "005930",
    bsns_year: str = "2024",
    reprt_code: str = "11011",
    account_nm: str = "당기순이익",
    fs_div: str = "CFS",
    sj_div: str = "IS",
    thstrm_amount: str = "50,000,000,000",
) -> dict:
    """DART 재무제표 mock item을 생성한다."""
    return {
        "rcept_no": "20250315000001",
        "corp_code": corp_code,
        "stock_code": stock_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "account_nm": account_nm,
        "fs_div": fs_div,
        "fs_nm": "연결재무제표" if fs_div == "CFS" else "재무제표",
        "sj_div": sj_div,
        "sj_nm": "손익계산서" if sj_div == "IS" else "재무상태표",
        "thstrm_nm": "제 56 기",
        "thstrm_dt": "2024.12.31",
        "thstrm_amount": thstrm_amount,
        "thstrm_add_amount": "",
        "frmtrm_nm": "제 55 기",
        "frmtrm_dt": "2023.12.31",
        "frmtrm_amount": "40,000,000,000",
        "frmtrm_add_amount": "",
        "ord": "1",
        "currency": "KRW",
    }


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """RateLimiter 인스턴스."""
    return RateLimiter(tps_limit=10.0, daily_limit=20_000)


@pytest.fixture
def source(rate_limiter: RateLimiter) -> DARTSource:
    """DARTSource 인스턴스."""
    return DARTSource(
        api_key="test-dart-api-key-0123456789abcdef01",
        rate_limiter=rate_limiter,
        max_retries=2,
    )


# -- classify_error ----------------------------------------------------


class TestClassifyError:
    """DART 에러 코드 분류 테스트."""

    def test_normal(self) -> None:
        """000은 OK로 분류한다."""
        assert classify_error("000") == ErrorAction.OK

    def test_unregistered_key(self) -> None:
        """010은 CRITICAL로 분류한다."""
        assert classify_error("010") == ErrorAction.CRITICAL

    def test_no_data(self) -> None:
        """013은 NO_DATA로 분류한다."""
        assert classify_error("013") == ErrorAction.NO_DATA

    def test_daily_limit(self) -> None:
        """020은 DAILY_LIMIT으로 분류한다."""
        assert classify_error("020") == ErrorAction.DAILY_LIMIT

    def test_excess_companies(self) -> None:
        """021은 SKIP으로 분류한다."""
        assert classify_error("021") == ErrorAction.SKIP

    def test_invalid_field(self) -> None:
        """100은 SKIP으로 분류한다."""
        assert classify_error("100") == ErrorAction.SKIP

    def test_system_maintenance(self) -> None:
        """800은 RETRY로 분류한다."""
        assert classify_error("800") == ErrorAction.RETRY

    def test_undefined_error(self) -> None:
        """900은 RETRY_ONCE로 분류한다 (1회 재시도 후 스킵, #2027)."""
        assert classify_error("900") == ErrorAction.RETRY_ONCE

    def test_expired_account(self) -> None:
        """901은 CRITICAL로 분류한다."""
        assert classify_error("901") == ErrorAction.CRITICAL

    def test_unmapped_code_defaults_to_retry(self) -> None:
        """매핑되지 않은 코드는 RETRY로 분류한다."""
        assert classify_error("999") == ErrorAction.RETRY


# -- _parse_corp_code_zip ----------------------------------------------


class TestParseCorpCodeZip:
    """corp_code ZIP 파싱 테스트."""

    def test_parse_listed_companies(self) -> None:
        """상장사만 추출한다."""
        entries = [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "modify_date": "20240101",
            },
            {
                "corp_code": "00999999",
                "corp_name": "비상장회사",
                "stock_code": "",
                "modify_date": "20240101",
            },
            {
                "corp_code": "00126400",
                "corp_name": "SK하이닉스",
                "stock_code": "000660",
                "modify_date": "20240101",
            },
        ]
        zip_bytes = _make_corp_code_zip(entries)
        result = DARTSource._parse_corp_code_zip(zip_bytes)

        assert len(result) == 2
        assert result["00126380"] == "005930"
        assert result["00126400"] == "000660"
        assert "00999999" not in result

    def test_parse_empty_zip(self) -> None:
        """항목이 없으면 빈 딕셔너리를 반환한다."""
        zip_bytes = _make_corp_code_zip([])
        result = DARTSource._parse_corp_code_zip(zip_bytes)
        assert result == {}

    def test_parse_all_unlisted(self) -> None:
        """모두 비상장사이면 빈 딕셔너리를 반환한다."""
        entries = [
            {
                "corp_code": "00999999",
                "corp_name": "비상장A",
                "stock_code": "",
                "modify_date": "20240101",
            },
            {
                "corp_code": "00999998",
                "corp_name": "비상장B",
                "stock_code": "  ",
                "modify_date": "20240101",
            },
        ]
        zip_bytes = _make_corp_code_zip(entries)
        result = DARTSource._parse_corp_code_zip(zip_bytes)
        assert result == {}


# -- _extract_list -----------------------------------------------------


class TestExtractList:
    """DART 응답 list 추출 테스트."""

    def test_multiple_items(self) -> None:
        """여러 item을 추출한다."""
        data = _make_financial_response(
            [_make_financial_item(), _make_financial_item(corp_code="00126400")]
        )
        items = DARTSource._extract_list(data)
        assert len(items) == 2

    def test_single_item_as_dict(self) -> None:
        """단일 item이 dict로 올 경우 list로 감싼다."""
        data = {"status": "000", "message": "정상", "list": _make_financial_item()}
        items = DARTSource._extract_list(data)
        assert len(items) == 1

    def test_empty_list(self) -> None:
        """list가 비어있으면 빈 리스트를 반환한다."""
        data = {"status": "000", "message": "정상", "list": []}
        items = DARTSource._extract_list(data)
        assert items == []

    def test_no_list_key(self) -> None:
        """list 키가 없으면 빈 리스트를 반환한다."""
        data = {"status": "013", "message": "조회된 데이터 없음"}
        items = DARTSource._extract_list(data)
        assert items == []


# -- _backoff_delay ----------------------------------------------------


class TestBackoffDelay:
    """Exponential Backoff + Full Jitter 테스트."""

    def test_attempt_0_bounded(self) -> None:
        """attempt=0일 때 0~1초 사이 값을 반환한다."""
        for _ in range(100):
            delay = DARTSource._backoff_delay(0, base=1.0, cap=60.0)
            assert 0 <= delay <= 1.0

    def test_cap_limits_delay(self) -> None:
        """cap 이상의 값을 반환하지 않는다."""
        for _ in range(100):
            delay = DARTSource._backoff_delay(10, base=1.0, cap=5.0)
            assert 0 <= delay <= 5.0


# -- fetch_corp_codes --------------------------------------------------


class TestFetchCorpCodes:
    """fetch_corp_codes 테스트 (mock HTTP)."""

    @pytest.mark.asyncio
    async def test_success(self, source: DARTSource) -> None:
        """정상적으로 고유번호 매핑을 반환한다."""
        entries = [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "modify_date": "20240101",
            },
        ]
        zip_bytes = _make_corp_code_zip(entries)

        with patch.object(
            source,
            "_download_corp_code_zip",
            new_callable=AsyncMock,
            return_value=zip_bytes,
        ):
            result = await source.fetch_corp_codes()

        assert result == {"00126380": "005930"}

    @pytest.mark.asyncio
    async def test_saves_to_file(self, source: DARTSource, tmp_path) -> None:
        """save_path가 주어지면 JSON 파일로 저장한다."""
        entries = [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "modify_date": "20240101",
            },
        ]
        zip_bytes = _make_corp_code_zip(entries)
        save_path = tmp_path / "dart_corp_codes.json"

        with patch.object(
            source,
            "_download_corp_code_zip",
            new_callable=AsyncMock,
            return_value=zip_bytes,
        ):
            result = await source.fetch_corp_codes(save_path=save_path)

        assert save_path.exists()
        saved = json.loads(save_path.read_text(encoding="utf-8"))
        assert saved == {"00126380": "005930"}
        assert result == saved

    @pytest.mark.asyncio
    async def test_daily_limit_raises(self, source: DARTSource) -> None:
        """일일 한도 도달 시 DailyLimitExceededError를 발생시킨다."""
        for _ in range(18000):
            source.rate_limiter.increment_daily()

        with pytest.raises(DailyLimitExceededError):
            await source.fetch_corp_codes()


# -- fetch_financial ---------------------------------------------------


class TestFetchFinancial:
    """fetch_financial 테스트 (mock HTTP)."""

    @pytest.mark.asyncio
    async def test_single_batch(self, source: DARTSource) -> None:
        """100개 이하 corp_codes는 단일 배치로 처리한다."""
        items = [
            _make_financial_item(corp_code="00126380", account_nm="당기순이익"),
            _make_financial_item(corp_code="00126380", account_nm="자본총계"),
        ]
        response = _make_financial_response(items)

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch_financial(["00126380"], "2024", "11011")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_multi_batch(self, source: DARTSource) -> None:
        """100개 초과 corp_codes는 여러 배치로 나누어 처리한다."""
        corp_codes = [f"{i:08d}" for i in range(150)]
        response = _make_financial_response([_make_financial_item()])

        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            return response

        with patch.object(source, "_do_request", side_effect=mock_request):
            await source.fetch_financial(corp_codes, "2024", "11011")

        # 150개 = 100 + 50 → 2 배치
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, source: DARTSource) -> None:
        """데이터 없음(013) 응답 시 빈 리스트를 반환한다."""
        response = {"status": "013", "message": "조회된 데이터 없음"}

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch_financial(["00126380"], "2024", "11013")

        assert result == []

    @pytest.mark.asyncio
    async def test_critical_error_raises(self, source: DARTSource) -> None:
        """인증키 에러(010) 시 CriticalApiError를 발생시킨다."""
        response = {"status": "010", "message": "등록되지 않은 키"}

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(CriticalApiError):
                await source.fetch_financial(["00126380"], "2024", "11011")

    @pytest.mark.asyncio
    async def test_daily_limit_error_raises(self, source: DARTSource) -> None:
        """일일 한도 초과(020) 시 DailyLimitExceededError를 발생시킨다."""
        response = {"status": "020", "message": "요청 제한 초과"}

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(DailyLimitExceededError):
                await source.fetch_financial(["00126380"], "2024", "11011")

    @pytest.mark.asyncio
    async def test_skip_error_raises(self, source: DARTSource) -> None:
        """재시도 불가 에러(100) 시 DARTError를 발생시킨다."""
        response = {"status": "100", "message": "부적절한 필드 값"}

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            with pytest.raises(DARTError):
                await source.fetch_financial(["00126380"], "2024", "11011")

    @pytest.mark.asyncio
    async def test_retry_then_success(self, source: DARTSource) -> None:
        """재시도 가능 에러 후 성공하면 데이터를 반환한다."""
        error_response = {"status": "800", "message": "시스템 점검 중"}
        success_response = _make_financial_response([_make_financial_item()])

        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return error_response
            return success_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                result = await source.fetch_financial(["00126380"], "2024", "11011")

        assert len(result) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self, source: DARTSource) -> None:
        """재시도 소진 시 DARTError를 발생시킨다."""
        error_response = {"status": "900", "message": "정의되지 않은 오류"}

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=error_response
        ):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

    @pytest.mark.asyncio
    async def test_network_error_retries(self, source: DARTSource) -> None:
        """네트워크 에러 시 재시도 후 성공하면 데이터를 반환한다."""
        import aiohttp

        success_response = _make_financial_response([_make_financial_item()])
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientConnectionError("Connection refused")
            return success_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                result = await source.fetch_financial(["00126380"], "2024", "11011")

        assert len(result) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_daily_limit_mid_batch_raises(self, source: DARTSource) -> None:
        """배치 처리 중 일일 한도 도달 시 DailyLimitExceededError를 발생시킨다."""
        corp_codes = [f"{i:08d}" for i in range(150)]
        response = _make_financial_response([_make_financial_item()])

        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            # 첫 번째 배치 후 한도 90% 도달 설정
            for _ in range(18000):
                source.rate_limiter.increment_daily()
            return response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with pytest.raises(DailyLimitExceededError):
                await source.fetch_financial(corp_codes, "2024", "11011")

        # 첫 번째 배치만 실행됨
        assert call_count == 1


# -- HTTP status 재시도 분류 (#2026) -----------------------------------


def _client_response_error(status: int) -> aiohttp.ClientResponseError:
    """지정 status를 가진 aiohttp.ClientResponseError를 생성한다."""
    request_info = aiohttp.RequestInfo(
        url=URL("https://opendart.fss.or.kr/test"),
        method="GET",
        headers=CIMultiDict(),
        real_url=URL("https://opendart.fss.or.kr/test"),
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
        self, source: DARTSource, status: int
    ) -> None:
        """400/401/403/404/422는 재시도 없이 1회 호출 후 즉시 실패한다."""
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            raise _client_response_error(status)

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        assert call_count == 1

    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
    @pytest.mark.asyncio
    async def test_retryable_status_retries(
        self, source: DARTSource, status: int
    ) -> None:
        """408/429/5xx ClientResponseError는 max_retries까지 재시도한다."""
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            raise _client_response_error(status)

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        assert call_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_timeout_error_retries(self, source: DARTSource) -> None:
        """TimeoutError는 재시도 대상이다."""
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timed out")

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        assert call_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_connection_error_without_status_retries(
        self, source: DARTSource
    ) -> None:
        """status 없는 ClientConnectionError(연결 오류)는 재시도 대상이다."""
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            raise aiohttp.ClientConnectionError("Connection refused")

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        assert call_count == source._max_retries == 2


# -- UNDEFINED(900) RETRY_ONCE 1회 재시도 cap (#2027) ------------------


class TestRetryOnceCap:
    """#2027: status=900(정의되지 않은 오류)는 1회만 재시도(총 2회 호출) 후 스킵."""

    @pytest.mark.asyncio
    async def test_undefined_status_retries_once_then_skips(
        self, rate_limiter: RateLimiter
    ) -> None:
        """900은 max_retries(=3)와 무관하게 2회 호출(1회 재시도) 후 실패한다."""
        source = DARTSource(
            api_key="test-dart-api-key-0123456789abcdef01",
            rate_limiter=rate_limiter,
            max_retries=3,
        )
        error_response = {"status": "900", "message": "정의되지 않은 오류"}
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            return error_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        # RETRY_ONCE → 최초 1회 + 재시도 1회 = 총 2회 (max_retries=3 미사용)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_general_retry_status_uses_max_retries(
        self, rate_limiter: RateLimiter
    ) -> None:
        """일반 RETRY status(800)는 max_retries(=3) 전체를 사용한다 (회귀)."""
        source = DARTSource(
            api_key="test-dart-api-key-0123456789abcdef01",
            rate_limiter=rate_limiter,
            max_retries=3,
        )
        error_response = {"status": "800", "message": "시스템 점검 중"}
        call_count = 0

        async def mock_request(session, url, params):
            nonlocal call_count
            call_count += 1
            return error_response

        with patch.object(source, "_do_request", side_effect=mock_request):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        assert call_count == 3


# -- corp_code 다운로드 경로 retry 정책 대칭 (#2026/#2027) ---------------


class _FakeJsonErrorResponse:
    """_download_corp_code_zip의 session.get(...) JSON 에러 응답 모킹."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.content_type = "application/json"

    async def __aenter__(self) -> _FakeJsonErrorResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        return self._body


class TestCorpCodeRetryPolicy:
    """corp_code ZIP 다운로드 경로에도 #2026/#2027이 동형 적용된다."""

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    @pytest.mark.asyncio
    async def test_non_retryable_status_fails_immediately(
        self, source: DARTSource, status: int
    ) -> None:
        """전송 단계 4xx는 재시도 없이 1회 호출 후 즉시 실패한다 (#2026)."""
        call_count = 0

        def fake_get(url, params=None):
            nonlocal call_count
            call_count += 1
            raise _client_response_error(status)

        with patch("aiohttp.ClientSession.get", side_effect=fake_get):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError):
                    await source.fetch_corp_codes()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_undefined_status_retries_once_then_skips(
        self, rate_limiter: RateLimiter
    ) -> None:
        """JSON status=900은 max_retries(=3)와 무관하게 2회 호출 후 실패한다 (#2027)."""
        source = DARTSource(
            api_key="test-dart-api-key-0123456789abcdef01",
            rate_limiter=rate_limiter,
            max_retries=3,
        )
        body = json.dumps({"status": "900", "message": "정의되지 않은 오류"})
        call_count = 0

        def fake_get(url, params=None):
            nonlocal call_count
            call_count += 1
            return _FakeJsonErrorResponse(body)

        with patch("aiohttp.ClientSession.get", side_effect=fake_get):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_corp_codes()

        assert call_count == 2


# -- daily_count attempt 기준 카운팅 (#2106) ----------------------------


class _FakeZipResponse:
    """_download_corp_code_zip의 session.get(...) async context manager 모킹.

    ZIP 바이너리 응답을 흉내낸다 (content_type='application/zip').
    """

    def __init__(self, zip_bytes: bytes) -> None:
        self._zip_bytes = zip_bytes
        self.content_type = "application/zip"

    async def __aenter__(self) -> _FakeZipResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._zip_bytes


class TestDailyCountAttemptCounting:
    """모든 실제 HTTP 호출 경로에서 daily_count가 attempt 기준으로 증가한다.

    실패/재시도 attempt도 카운트되고, 성공 시 1 attempt = 1 increment로
    이중 카운트가 없어야 한다 (#2106).
    """

    # -- financial (_fetch_multi_acnt) 경로 --

    @pytest.mark.asyncio
    async def test_financial_failed_attempts_counted(self, source: DARTSource) -> None:
        """financial: _do_request가 항상 실패해도 attempt 수만큼 카운트된다."""
        import aiohttp

        async def always_fail(session, url, params):
            raise aiohttp.ClientConnectionError("Connection refused")

        with patch.object(source, "_do_request", side_effect=always_fail):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_financial(["00126380"], "2024", "11011")

        # max_retries=2 → 실패해도 2회 카운트 (기존엔 0)
        assert source.rate_limiter.daily_count == source._max_retries == 2

    @pytest.mark.asyncio
    async def test_financial_success_counts_once(self, source: DARTSource) -> None:
        """financial: 단일 배치 성공 → daily_count == 1 (이중 카운트 없음)."""
        response = _make_financial_response([_make_financial_item()])

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            await source.fetch_financial(["00126380"], "2024", "11011")

        assert source.rate_limiter.daily_count == 1

    @pytest.mark.asyncio
    async def test_financial_multi_batch_counts_per_batch(
        self, source: DARTSource
    ) -> None:
        """financial: 150 corp(2배치) 성공 → daily_count == 배치 수(2)."""
        corp_codes = [f"{i:08d}" for i in range(150)]
        response = _make_financial_response([_make_financial_item()])

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            await source.fetch_financial(corp_codes, "2024", "11011")

        assert source.rate_limiter.daily_count == 2

    # -- corp_code ZIP download (_download_corp_code_zip) 경로 --

    @pytest.mark.asyncio
    async def test_corp_code_success_counts_once(self, source: DARTSource) -> None:
        """corp_code: ZIP 다운로드 성공 1회 → daily_count == 1.

        성공 후 외부 increment를 제거하고 attempt 내부 카운트로 일원화했으므로
        이중 카운트가 없어야 한다 (#2106).
        """
        zip_bytes = _make_corp_code_zip(
            [{"corp_code": "00126380", "stock_code": "005930"}]
        )

        with patch(
            "aiohttp.ClientSession.get",
            return_value=_FakeZipResponse(zip_bytes),
        ):
            result = await source.fetch_corp_codes()

        assert result == {"00126380": "005930"}
        assert source.rate_limiter.daily_count == 1

    @pytest.mark.asyncio
    async def test_corp_code_failed_attempts_counted(self, source: DARTSource) -> None:
        """corp_code: download가 항상 실패해도 attempt 수만큼 카운트된다."""
        import aiohttp

        with patch(
            "aiohttp.ClientSession.get",
            side_effect=aiohttp.ClientConnectionError("Connection refused"),
        ):
            with patch.object(source, "_backoff_delay", return_value=0.0):
                with pytest.raises(DARTError, match="최종 실패"):
                    await source.fetch_corp_codes()

        # max_retries=2 → 실패해도 2회 카운트 (기존엔 0)
        assert source.rate_limiter.daily_count == source._max_retries == 2


# -- fetch (DataSource 프로토콜) ----------------------------------------


class TestFetch:
    """DataSource 프로토콜 fetch() 테스트."""

    @pytest.mark.asyncio
    async def test_delegates_to_fetch_financial(self, source: DARTSource) -> None:
        """fetch()는 kwargs를 fetch_financial에 전달한다."""
        response = _make_financial_response([_make_financial_item()])

        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            result = await source.fetch(
                "2024-12-31",
                corp_codes=["00126380"],
                year="2024",
                reprt_code="11011",
            )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_missing_kwargs_returns_empty(self, source: DARTSource) -> None:
        """필수 kwargs가 없으면 빈 리스트를 반환한다."""
        result = await source.fetch("2024-12-31")
        assert result == []

    @pytest.mark.asyncio
    async def test_partial_kwargs_returns_empty(self, source: DARTSource) -> None:
        """일부 kwargs만 있으면 빈 리스트를 반환한다."""
        result = await source.fetch("2024-12-31", corp_codes=["00126380"])
        assert result == []


# -- validate_credentials (#2046) --------------------------------------


class TestValidateCredentials:
    """DART 키 유효성 3-state 검증 (mock HTTP, 실 네트워크 없음)."""

    @pytest.mark.asyncio
    async def test_valid_key_ok(self, source: DARTSource) -> None:
        """정상 응답(000) → valid=True."""
        response = _make_financial_response([_make_financial_item()], status="000")
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, detail = await source.validate_credentials()
        assert valid is True
        assert detail is None

    @pytest.mark.asyncio
    async def test_valid_key_no_data(self, source: DARTSource) -> None:
        """데이터 없음(013)도 키는 수락된 것 → valid=True."""
        response = _make_financial_response([], status="013", message="데이터 없음")
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, detail = await source.validate_credentials()
        assert valid is True
        assert detail is None

    @pytest.mark.asyncio
    async def test_invalid_key_010(self, source: DARTSource) -> None:
        """미등록 키(010) → valid=False, 사유 포함."""
        response = _make_financial_response(
            [], status="010", message="등록되지 않은 키입니다"
        )
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, detail = await source.validate_credentials()
        assert valid is False
        assert detail is not None
        assert "010" in detail

    @pytest.mark.asyncio
    async def test_invalid_key_011_unusable(self, source: DARTSource) -> None:
        """사용 불가 키(011)도 인증 실패 → valid=False."""
        response = _make_financial_response(
            [], status="011", message="사용할 수 없는 키"
        )
        with patch.object(
            source, "_do_request", new_callable=AsyncMock, return_value=response
        ):
            valid, _ = await source.validate_credentials()
        assert valid is False

    @pytest.mark.asyncio
    async def test_network_error_unknown(self, source: DARTSource) -> None:
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
    async def test_timeout_unknown(self, source: DARTSource) -> None:
        """타임아웃 → valid=None(검증 불가), 예외 미전파."""

        async def _slow(*args: object, **kwargs: object) -> dict:
            raise TimeoutError

        with patch.object(source, "_do_request", side_effect=_slow):
            valid, detail = await source.validate_credentials()
        assert valid is None
        assert detail is not None
