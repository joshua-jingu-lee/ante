"""KIS API 에러 처리 테스트 — 재시도, Circuit Breaker, 타임아웃, 에러 분류."""

import asyncio
import time

import pytest

from ante.broker.circuit_breaker import CircuitBreaker, CircuitState
from ante.broker.error_codes import (
    get_error_message,
    is_retryable_http_status,
    is_retryable_msg_code,
)
from ante.broker.exceptions import APIError, CircuitOpenError
from ante.eventbus import EventBus
from ante.eventbus.events import (
    CircuitBreakerEvent,
    OrderCancelFailedEvent,
)

# ── US-5: 에러코드 분류 체계 ──────────────────────


class TestErrorCodeClassification:
    def test_permanent_msg_code_not_retryable(self):
        """잔고 부족 등 permanent 에러는 재시도 불가."""
        assert is_retryable_msg_code("APBK0919") is False  # 잔고 부족
        assert is_retryable_msg_code("APBK0013") is False  # 잘못된 종목코드
        assert is_retryable_msg_code("APBK1002") is False  # 시장 마감

    def test_transient_msg_code_retryable(self):
        """서버 과부하 등 transient 에러는 재시도 가능."""
        assert is_retryable_msg_code("APBK0600") is True  # 서버 과부하
        assert is_retryable_msg_code("APBK0601") is True  # 처리 지연

    def test_unknown_msg_code_retryable(self):
        """알 수 없는 코드는 재시도 가능 (보수적)."""
        assert is_retryable_msg_code("UNKNOWN_CODE") is True

    def test_retryable_http_status(self):
        """5xx, 429는 재시도 가능."""
        assert is_retryable_http_status(500) is True
        assert is_retryable_http_status(502) is True
        assert is_retryable_http_status(503) is True
        assert is_retryable_http_status(429) is True

    def test_non_retryable_http_status(self):
        """4xx는 재시도 불가."""
        assert is_retryable_http_status(400) is False
        assert is_retryable_http_status(401) is False
        assert is_retryable_http_status(403) is False
        assert is_retryable_http_status(404) is False

    def test_api_error_retryable_attribute(self):
        """APIError에 retryable 속성 존재."""
        err_retryable = APIError("test", retryable=True)
        assert err_retryable.retryable is True

        err_permanent = APIError("test", retryable=False)
        assert err_permanent.retryable is False

    def test_api_error_default_not_retryable(self):
        """APIError 기본값은 retryable=False."""
        err = APIError("test")
        assert err.retryable is False

    def test_error_message_known_code(self):
        """알려진 에러코드에 한글 메시지 반환."""
        assert get_error_message("APBK0919") == "잔고 부족"
        assert get_error_message("APBK1002") == "시장 마감"

    def test_error_message_unknown_code(self):
        """알 수 없는 에러코드에 fallback 메시지."""
        msg = get_error_message("UNKNOWN", fallback="커스텀 메시지")
        assert msg == "커스텀 메시지"

        msg2 = get_error_message("UNKNOWN")
        assert "알 수 없는 에러" in msg2

    def test_insufficient_deposit_constant(self):
        """예수금 부족 코드 상수 확인."""
        from ante.broker.error_codes import INSUFFICIENT_DEPOSIT_CODE

        assert INSUFFICIENT_DEPOSIT_CODE == "APBK0919"

    def test_is_insufficient_deposit(self):
        """예수금 부족 에러 판별."""
        from ante.broker.error_codes import is_insufficient_deposit

        assert is_insufficient_deposit("APBK0919") is True
        assert is_insufficient_deposit("APBK0013") is False
        assert is_insufficient_deposit("") is False


# ── US-2: Circuit Breaker ──────────────────────────


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        """초기 상태는 CLOSED."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        """threshold 미만 실패 시 CLOSED 유지."""
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        """threshold 도달 시 OPEN."""
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_check(self):
        """OPEN 상태에서 check() → CircuitOpenError."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_half_open_after_recovery_timeout(self):
        """recovery_timeout 후 HALF_OPEN으로 전환."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        """HALF_OPEN에서 성공 → CLOSED."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        _ = cb.state  # trigger HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self):
        """HALF_OPEN에서 실패 → OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        _ = cb.state  # trigger HALF_OPEN

        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """성공 시 failure_count 리셋."""
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0

    async def test_circuit_breaker_event_published(self):
        """상태 변경 시 CircuitBreakerEvent 발행."""
        eventbus = EventBus()
        cb = CircuitBreaker(failure_threshold=2, eventbus=eventbus, name="test")

        received: list[CircuitBreakerEvent] = []
        eventbus.subscribe(CircuitBreakerEvent, lambda e: received.append(e))

        cb.record_failure()
        cb.record_failure()  # OPEN 전환
        await asyncio.sleep(0.01)  # fire-and-forget task 완료 대기

        assert len(received) == 1
        assert received[0].old_state == "closed"
        assert received[0].new_state == "open"
        assert received[0].broker == "test"

    def test_check_passes_when_closed(self):
        """CLOSED 상태에서 check()는 예외 없음."""
        cb = CircuitBreaker()
        cb.check()  # 예외 없이 통과

    def test_check_passes_when_half_open(self):
        """HALF_OPEN 상태에서 check()는 예외 없음 (시험 허용)."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.check()  # HALF_OPEN으로 전환 후 통과


# ── US-4: 주문 취소 실패 이벤트 ────────────────────


class TestOrderCancelFailedEvent:
    def test_event_fields(self):
        """OrderCancelFailedEvent 필드 확인."""
        event = OrderCancelFailedEvent(
            order_id="ord1",
            bot_id="bot1",
            strategy_id="s1",
            error_message="취소 실패",
        )
        assert event.order_id == "ord1"
        assert event.bot_id == "bot1"
        assert event.error_message == "취소 실패"

    async def test_cancel_failed_event_published(self):
        """취소 실패 시 OrderCancelFailedEvent 발행."""
        eventbus = EventBus()
        received: list[OrderCancelFailedEvent] = []
        eventbus.subscribe(OrderCancelFailedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderCancelFailedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                error_message="network error",
            )
        )

        assert len(received) == 1
        assert received[0].error_message == "network error"


# ── US-3: 타임아웃 설정 ────────────────────────────


class TestTimeoutConfig:
    def test_default_timeout_values(self):
        """config/defaults.py에 타임아웃 기본값 포함."""
        from ante.config.defaults import DEFAULTS

        assert DEFAULTS["broker.timeout.order"] == 10
        assert DEFAULTS["broker.timeout.query"] == 5
        assert DEFAULTS["broker.timeout.auth"] == 10

    def test_default_retry_values(self):
        """config/defaults.py에 재시도 기본값 포함."""
        from ante.config.defaults import DEFAULTS

        assert DEFAULTS["broker.retry.max_retries_order"] == 3
        assert DEFAULTS["broker.retry.max_retries_query"] == 2
        assert DEFAULTS["broker.retry.max_retries_auth"] == 2
        assert DEFAULTS["broker.retry.backoff_base_seconds"] == 1.0

    def test_default_circuit_breaker_values(self):
        """config/defaults.py에 circuit breaker 기본값 포함."""
        from ante.config.defaults import DEFAULTS

        assert DEFAULTS["broker.circuit_breaker.failure_threshold"] == 5
        assert DEFAULTS["broker.circuit_breaker.recovery_timeout"] == 60


# ── US-1: 재시도 로직 (KISAdapter._request 단위) ────


class TestRetryLogic:
    def test_kis_adapter_has_retry_config(self):
        """KISAdapter가 재시도 설정을 가진다."""
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter.__new__(KISAdapter)
        adapter._max_retries_order = 3
        adapter._max_retries_query = 2
        adapter._max_retries_auth = 2
        adapter._backoff_base = 1.0

        assert adapter._max_retries_order == 3
        assert adapter._max_retries_query == 2
        assert adapter._backoff_base == 1.0

    def test_kis_adapter_has_timeout_config(self):
        """KISAdapter가 타임아웃 설정을 가진다."""
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter.__new__(KISAdapter)
        adapter._timeout_order = 10
        adapter._timeout_query = 5
        adapter._timeout_auth = 10

        assert adapter._timeout_order == 10
        assert adapter._timeout_query == 5

    def test_kis_adapter_has_circuit_breaker(self):
        """KISAdapter가 circuit breaker를 가진다."""
        from ante.broker.kis import KISAdapter

        config = {
            "app_key": "test",
            "app_secret": "test",
            "account_no": "1234567890",
            "is_paper": True,
        }
        adapter = KISAdapter(config=config)
        assert adapter.circuit_breaker is not None
        assert adapter.circuit_breaker.state == CircuitState.CLOSED

    def test_kis_adapter_custom_config(self):
        """KISAdapter 커스텀 설정."""
        from ante.broker.kis import KISAdapter

        config = {
            "app_key": "test",
            "app_secret": "test",
            "account_no": "1234567890",
            "retry.max_retries_order": 5,
            "timeout.order": 15,
            "circuit_breaker.failure_threshold": 10,
        }
        adapter = KISAdapter(config=config)
        assert adapter._max_retries_order == 5
        assert adapter._timeout_order == 15
        assert adapter._circuit_breaker._failure_threshold == 10


# ── CircuitBreakerEvent 필드 ──────────────────────


class TestCircuitBreakerEvent:
    def test_event_fields(self):
        """CircuitBreakerEvent 필드 확인."""
        event = CircuitBreakerEvent(
            broker="kis",
            old_state="closed",
            new_state="open",
            failure_count=5,
            reason="연속 5회 실패",
        )
        assert event.broker == "kis"
        assert event.old_state == "closed"
        assert event.new_state == "open"
        assert event.failure_count == 5


# ── Gateway 취소 실패 통합 ──────────────────────────


class TestGatewayCancelFailed:
    async def test_cancel_failure_publishes_event(self):
        """Gateway 취소 실패 시 OrderCancelFailedEvent 발행."""
        from unittest.mock import AsyncMock

        from ante.eventbus.events import OrderCancelEvent
        from ante.gateway import APIGateway

        eventbus = EventBus()
        mock_broker = AsyncMock()
        mock_broker.cancel_order = AsyncMock(side_effect=Exception("network error"))

        gw = APIGateway(broker=mock_broker, eventbus=eventbus)
        gw.start()

        received: list[OrderCancelFailedEvent] = []
        eventbus.subscribe(OrderCancelFailedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderCancelEvent(
                bot_id="bot1",
                strategy_id="s1",
                order_id="ord1",
                reason="test cancel",
            )
        )

        assert len(received) == 1
        assert received[0].order_id == "ord1"
        assert received[0].bot_id == "bot1"
        assert "network error" in received[0].error_message


# ── Bot 취소 실패 전달 ──────────────────────────────


class TestBotCancelFailedHandling:
    async def test_bot_receives_cancel_failed(self):
        """Bot이 OrderCancelFailedEvent를 전략에 cancel_failed로 전달."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.bot.bot import Bot
        from ante.bot.config import BotConfig

        mock_strategy = MagicMock()
        mock_strategy.on_order_update = AsyncMock()

        eventbus = EventBus()
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            bot_type="paper",
        )
        bot = Bot(
            config=config,
            strategy_cls=MagicMock(),
            ctx=MagicMock(),
            eventbus=eventbus,
        )
        bot.strategy = mock_strategy

        await bot.on_order_update(
            OrderCancelFailedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                error_message="cancel failed",
            )
        )

        mock_strategy.on_order_update.assert_called_once()
        call_args = mock_strategy.on_order_update.call_args[0][0]
        assert call_args["status"] == "cancel_failed"
        assert call_args["order_id"] == "ord1"
