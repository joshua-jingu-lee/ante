"""KIS 요청이 보내는 순간의 토큰을 만료 여유 밖으로 유지하는지 (#2901).

속도 제한 대기·재시도 백오프가 만료 여유(5분)를 넘어도 매 시도의 헤더를 만들기
직전에 인증을 다시 확인하고 헤더를 다시 만든다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest

import ante.broker.kis as kis_module
from ante.broker import KISAdapter
from ante.broker.exceptions import APIError, TokenRateLimitError
from ante.broker.kis import (
    _raise_token_rate_limit,
    _record_token_cooldown,
    _reset_token_cache,
)
from ante.core import clock

_WALL_AT = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
_OLD_TOKEN = "fake-old-token"
_NEW_TOKEN = "fake-new-token"
_QUERY_TR_ID = "FAKEQUERY01"
_ORDER_TR_ID = "VTTC0012U"
_URL = "https://example.invalid/uapi/fake"


class _Clock:
    """벽시계와 단조 시계를 함께 진행시키는 시계 대역."""

    def __init__(self) -> None:
        self._at = _WALL_AT
        self._monotonic = 1000.0

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self._at.astimezone().replace(tzinfo=None)
        return self._at.astimezone(tz)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)
        self._monotonic += seconds


@pytest.fixture(autouse=True)
def _isolate_token_cache() -> Iterator[None]:
    _reset_token_cache()
    yield
    _reset_token_cache()


@pytest.fixture
def fake_clock() -> Iterator[_Clock]:
    with clock.use_clock(_Clock()) as installed:
        yield installed


@pytest.fixture
def slept(fake_clock: _Clock, monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """잔 만큼 시계를 진행시키는 가짜 sleep (요청 창 대기·재시도 백오프 공통)."""
    original_sleep = asyncio.sleep
    delays: list[float] = []

    async def _fake_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        delays.append(delay)
        fake_clock.advance(delay)
        await original_sleep(0)

    monkeypatch.setattr(kis_module.asyncio, "sleep", _fake_sleep)
    return delays


class _Harness:
    """HTTP 전송·토큰 발급·차단기 실패 기록을 가로채는 어댑터 대역."""

    def __init__(
        self,
        *,
        expires_in: timedelta,
        backoff_base: float = 1.0,
        send_errors: list[BaseException] | None = None,
        issue_error: bool = False,
    ) -> None:
        self.adapter = KISAdapter(
            {
                "app_key": "fake-app-key",
                "app_secret": "fake-app-secret",
                "account_no": "0000000001",
                "is_paper": True,
                "retry.backoff_base_seconds": backoff_base,
            }
        )
        self.adapter.access_token = _OLD_TOKEN
        self.adapter.token_expires_at = clock.now(UTC) + expires_in
        self.sent_headers: list[dict[str, str]] = []
        self.issued = 0
        self.failures = 0
        self._send_errors = list(send_errors or [])
        self._issue_error = issue_error

        async def _send_http(
            method: str,
            url: str,
            headers: dict[str, str],
            params: dict[str, str] | None,
            json_data: dict[str, Any] | None,
            timeout: float,
        ) -> tuple[dict[str, Any], str]:
            self.sent_headers.append(dict(headers))
            if self._send_errors:
                raise self._send_errors.pop(0)
            return {"rt_cd": "0"}, ""

        async def _issue_token() -> tuple[str, datetime]:
            self.issued += 1
            if self._issue_error:
                _raise_token_rate_limit(self.adapter.app_key)
            return _NEW_TOKEN, clock.now(UTC) + timedelta(hours=24)

        breaker = self.adapter._circuit_breaker
        original_record_failure = breaker.record_failure

        def _record_failure() -> None:
            self.failures += 1
            original_record_failure()

        self.adapter._send_http = _send_http  # type: ignore[method-assign]
        self.adapter._issue_token = _issue_token  # type: ignore[method-assign]
        breaker.record_failure = _record_failure  # type: ignore[method-assign]

    def fill_window(self) -> None:
        self.adapter._rate_limit_per_minute = 1
        self.adapter._request_times.append(clock.monotonic())

    def tokens(self) -> list[str]:
        return [h["authorization"] for h in self.sent_headers]


def _retryable() -> APIError:
    return APIError("HTTP 500: fake", status_code=500, retryable=True)


class TestTokenFreshAtSend:
    async def test_rate_limit_wait_past_margin_reissues_before_send(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """60초 대기 한 번으로 만료 여유를 넘으면 보내기 직전에 재발급한다."""
        h = _Harness(expires_in=timedelta(minutes=5, seconds=10))
        h.fill_window()

        await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID)

        assert slept == [60.0]
        assert h.tokens() == [f"Bearer {_NEW_TOKEN}"]
        assert h.issued == 1

    async def test_retry_backoff_past_margin_reissues_before_resend(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """재시도 백오프가 만료 여유를 넘으면 두 번째 시도는 새 토큰으로 나간다."""
        h = _Harness(
            expires_in=timedelta(minutes=5, seconds=10),
            backoff_base=30.0,
            send_errors=[_retryable()],
        )

        await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID)

        assert slept == [30.0]
        assert h.tokens() == [f"Bearer {_OLD_TOKEN}", f"Bearer {_NEW_TOKEN}"]
        assert h.issued == 1

    async def test_continuation_header_survives_retry(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """연속조회 헤더는 재시도마다 다시 만든 헤더에도 붙는다."""
        h = _Harness(
            expires_in=timedelta(minutes=5, seconds=10),
            backoff_base=30.0,
            send_errors=[_retryable()],
        )

        await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID, cont_header="N")

        assert [hd.get("tr_cont") for hd in h.sent_headers] == ["N", "N"]

    async def test_fresh_token_is_not_reissued_across_wait_and_retry(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """신선한 토큰이면 대기·재시도가 있어도 재발급하지 않고 헤더도 같다."""
        h = _Harness(
            expires_in=timedelta(hours=1),
            backoff_base=30.0,
            send_errors=[_retryable()],
        )
        h.fill_window()

        await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID)

        assert slept == [60.0, 30.0]
        assert h.issued == 0
        assert h.tokens() == [f"Bearer {_OLD_TOKEN}"] * 2
        assert h.sent_headers[0] == h.sent_headers[1]


class TestReauthFailureInsideRetry:
    async def test_reauth_failure_before_retry_propagates_without_resend(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """재시도 직전 재인증이 실패하면 그대로 전파하고 다시 보내지 않는다."""
        h = _Harness(
            expires_in=timedelta(minutes=5, seconds=10),
            backoff_base=30.0,
            send_errors=[_retryable()],
            issue_error=True,
        )

        with pytest.raises(TokenRateLimitError):
            await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID)

        assert len(h.sent_headers) == 1
        assert h.failures == 1
        assert h.issued == 1

    async def test_cooldown_fails_before_entering_rate_limit_queue(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """쿨다운 중 만료 여유 안의 토큰이면 줄을 서기 전에 즉시 실패한다."""
        h = _Harness(expires_in=timedelta(minutes=1))
        h.fill_window()
        _record_token_cooldown(h.adapter.app_key)

        with pytest.raises(TokenRateLimitError):
            await h.adapter._request_with_cont("GET", _URL, _QUERY_TR_ID)

        assert slept == []
        assert len(h.adapter._request_times) == 1
        assert h.sent_headers == []
        assert h.issued == 0

    async def test_order_timeout_then_reauth_failure_does_not_resend(
        self, fake_clock: _Clock, slept: list[float]
    ) -> None:
        """주문 시간 초과 뒤 재인증이 실패하면 전송은 한 번뿐이고 인증 오류로 끝난다."""
        h = _Harness(
            expires_in=timedelta(minutes=5, seconds=10),
            backoff_base=30.0,
            send_errors=[TimeoutError()],
            issue_error=True,
        )

        with pytest.raises(TokenRateLimitError):
            await h.adapter._request_with_cont(
                "POST", _URL, _ORDER_TR_ID, json_data={"fake": "order"}
            )

        assert len(h.sent_headers) == 1
        assert h.failures == 1
