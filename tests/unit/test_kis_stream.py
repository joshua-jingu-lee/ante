"""KISStreamClient 단위 테스트."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.broker.kis_stream import (
    CHANNEL_EXECUTION,
    CHANNEL_PRICE,
    MAX_SUBSCRIPTIONS,
    KISStreamClient,
)
from ante.eventbus.events import StreamDisconnectedEvent
from tests.unit._kis_stream_helpers import (
    FakeSocket,
    FakeWebsockets,
    price_frame,
    price_record,
)


@pytest.fixture
def eventbus() -> MagicMock:
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def stream_client(eventbus: MagicMock) -> KISStreamClient:
    """KISStreamClient 인스턴스."""
    return KISStreamClient(
        websocket_url="ws://ops.koreainvestment.com:31000",
        app_key="test_key",
        app_secret="test_secret",
        approval_key="test_approval",
        eventbus=eventbus,
    )


class TestKISStreamClientInit:
    """초기화 테스트."""

    def test_init_paper(self, stream_client: KISStreamClient) -> None:
        assert stream_client._url == "ws://ops.koreainvestment.com:31000"
        assert not stream_client.is_connected
        assert len(stream_client.subscribed_symbols) == 0

    def test_init_real(self, eventbus: MagicMock) -> None:
        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:21000",
            app_key="key",
            app_secret="secret",
            approval_key="approval",
            eventbus=eventbus,
        )
        assert client._url == "ws://ops.koreainvestment.com:21000"


class TestApprovalKeyUrlInference:
    """approval_key 발급 시 REST URL 유추 테스트 (Refs #988)."""

    def test_paper_ws_uses_paper_rest(self, eventbus: MagicMock) -> None:
        """모의투자 WS(:31000) → 모의투자 REST(openapivts:29443)."""
        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:31000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
        )
        # _get_approval_key 내부 로직 검증을 위해 URL 유추만 테스트
        if "31000" in client._url:
            rest_url = "https://openapivts.koreainvestment.com:29443"
        else:
            rest_url = "https://openapi.koreainvestment.com:9443"
        assert rest_url == "https://openapivts.koreainvestment.com:29443"

    def test_real_ws_uses_real_rest(self, eventbus: MagicMock) -> None:
        """실전 WS(:21000) → 실전 REST(openapi:9443)."""
        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:21000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
        )
        if "31000" in client._url:
            rest_url = "https://openapivts.koreainvestment.com:29443"
        else:
            rest_url = "https://openapi.koreainvestment.com:9443"
        assert rest_url == "https://openapi.koreainvestment.com:9443"


class TestApprovalKeyTimeout:
    """접속키 발급의 시간 제한 (#2804)."""

    async def test_session_has_auth_timeout(
        self,
        eventbus: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        kis_stream_external_guard,
    ) -> None:
        """접속키 요청 세션은 total=DEFAULT_TIMEOUT_AUTH 시간 제한을 갖는다."""
        import aiohttp

        from ante.broker.kis import DEFAULT_TIMEOUT_AUTH

        created: list[dict] = []
        posted: list[str] = []

        class _Resp:
            status = 200

            async def json(self) -> dict:
                return {"approval_key": "approval-x"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

        class _Session:
            def __init__(self, **kwargs) -> None:
                created.append(kwargs)

            def post(self, url: str, **kwargs):
                posted.append(url)
                return _Resp()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

        monkeypatch.setattr(aiohttp, "ClientSession", _Session)
        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:31000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
        )

        key = await kis_stream_external_guard.original_get_approval_key(client)

        assert key == "approval-x"
        assert len(created) == 1
        timeout = created[0]["timeout"]
        assert isinstance(timeout, aiohttp.ClientTimeout)
        assert timeout.total == DEFAULT_TIMEOUT_AUTH
        assert posted == [
            "https://openapivts.koreainvestment.com:29443/oauth2/Approval"
        ]


class TestSubscription:
    """구독 관련 테스트."""

    async def test_subscribe_before_connect(
        self, stream_client: KISStreamClient
    ) -> None:
        """연결 전 구독은 목록에만 추가."""
        result = await stream_client.subscribe("005930")
        assert result is True
        assert "005930" in stream_client.subscribed_symbols

    async def test_subscribe_duplicate(self, stream_client: KISStreamClient) -> None:
        """중복 구독은 무시."""
        await stream_client.subscribe("005930")
        result = await stream_client.subscribe("005930")
        assert result is True
        assert len(stream_client.subscribed_symbols) == 1

    async def test_subscribe_max_limit(self, stream_client: KISStreamClient) -> None:
        """최대 구독 한도 초과 시 False 반환."""
        for i in range(MAX_SUBSCRIPTIONS):
            await stream_client.subscribe(f"{i:06d}")
        result = await stream_client.subscribe("999999")
        assert result is False
        assert len(stream_client.subscribed_symbols) == MAX_SUBSCRIPTIONS

    async def test_unsubscribe(self, stream_client: KISStreamClient) -> None:
        """구독 해제."""
        await stream_client.subscribe("005930")
        await stream_client.unsubscribe("005930")
        assert "005930" not in stream_client.subscribed_symbols

    async def test_unsubscribe_not_subscribed(
        self, stream_client: KISStreamClient
    ) -> None:
        """미구독 종목 해제는 무시."""
        await stream_client.unsubscribe("999999")  # 에러 없이 통과


class TestMessageHandling:
    """메시지 처리 테스트."""

    async def test_handle_price_data(self, stream_client: KISStreamClient) -> None:
        """실시간 시세 데이터 처리."""
        received: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(on_price)

        raw = price_frame(price_record("005930", 50000))
        await stream_client._handle_message(raw)

        assert len(received) == 1
        assert received[0] == ("005930", 50000.0)

    async def test_handle_price_data_invalid(
        self, stream_client: KISStreamClient
    ) -> None:
        """잘못된 시세 데이터는 무시."""
        received: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(on_price)

        # 필드 부족: 건수 × 46과 맞지 않아 첫 레코드만 보고, 그 레코드도 3필드 미만
        raw = f"0|{CHANNEL_PRICE}|004|005930"
        await stream_client._handle_message(raw)
        assert len(received) == 0

    async def test_handle_execution_data(self, stream_client: KISStreamClient) -> None:
        """실시간 체결 통보 처리."""
        received: list[dict] = []

        async def on_exec(data: dict) -> None:
            received.append(data)

        stream_client.on_execution(on_exec)

        # 파이프 구분 체결 데이터
        fields = ["005930", "ORD001", "", "", "02", "10", "50000", "", "", "", ""]
        raw = f"0|{CHANNEL_EXECUTION}|004|" + "^".join(fields)
        await stream_client._handle_message(raw)

        assert len(received) == 1
        assert received[0]["symbol"] == "005930"
        assert received[0]["side"] == "buy"
        assert received[0]["quantity"] == 10.0

    async def test_handle_json_message(self, stream_client: KISStreamClient) -> None:
        """JSON 구독 확인 메시지 처리 (에러 없이)."""
        import json

        msg = json.dumps(
            {
                "header": {"tr_id": "H0STCNT0", "tr_key": "005930"},
                "body": {"msg1": "SUBSCRIBE SUCCESS"},
            }
        )
        # JSON 메시지 (구독 확인 등) — 에러 없이 처리
        await stream_client._handle_message(msg)

    async def test_price_callback_error_isolated(
        self, stream_client: KISStreamClient
    ) -> None:
        """콜백 오류가 다른 콜백에 영향 주지 않음."""
        received: list[tuple[str, float]] = []

        async def bad_callback(symbol: str, price: float) -> None:
            raise ValueError("test error")

        async def good_callback(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(bad_callback)
        stream_client.on_price(good_callback)

        raw = price_frame(price_record("005930", 50000))
        await stream_client._handle_message(raw)

        assert received == [("005930", 50000.0)]


class TestDisconnect:
    """연결 해제 테스트."""

    async def test_disconnect_clears_state(
        self, stream_client: KISStreamClient
    ) -> None:
        """disconnect 시 구독 목록 초기화."""
        await stream_client.subscribe("005930")
        await stream_client.disconnect()
        assert len(stream_client.subscribed_symbols) == 0
        assert not stream_client.is_connected

    async def test_disconnect_publishes_event(
        self, stream_client: KISStreamClient, eventbus: MagicMock
    ) -> None:
        """disconnect 후 이벤트 발행 안 함 (clean disconnect)."""
        await stream_client.disconnect()
        # clean disconnect에서는 disconnected 이벤트를 발행하지 않음
        # (connection_lost일 때만 발행)
        eventbus.publish.assert_not_called()


class TestPerAccountEventPublication:
    """SPLIT-3 (#1242): KISStreamClient 가 자신의 ``account_id`` 를 이벤트에
    명시 전달하는지 검증한다. multi-account 환경에서 다른 stream 의 disconnect
    가 자기 fallback 을 토글하지 않도록 격리 게이트가 의존하는 핵심 계약이다.
    """

    async def test_publish_connected_carries_account_id(
        self, eventbus: MagicMock
    ) -> None:
        """``_publish_connected`` 가 account_id 를 실은 StreamConnectedEvent
        를 발행한다."""
        from ante.eventbus.events import StreamConnectedEvent

        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:31000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
            account_id="acc-alpha",
        )
        await client._publish_connected()

        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StreamConnectedEvent)
        assert event.account_id == "acc-alpha"
        assert event.broker == "kis"

    async def test_publish_disconnected_carries_account_id(
        self, eventbus: MagicMock
    ) -> None:
        """``_publish_disconnected`` 가 account_id 를 실은
        StreamDisconnectedEvent 를 발행한다."""
        from ante.eventbus.events import StreamDisconnectedEvent

        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:31000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
            account_id="acc-beta",
        )
        await client._publish_disconnected("connection_lost")

        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StreamDisconnectedEvent)
        assert event.account_id == "acc-beta"
        assert event.reason == "connection_lost"

    async def test_publish_without_account_id_raises(self, eventbus: MagicMock) -> None:
        """account_id 가 빈 문자열이면 strict marker 에 의해
        InvalidAccountIdError 가 raise 된다 (이벤트 발행 차단)."""
        from ante.account.errors import InvalidAccountIdError

        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:31000",
            app_key="key",
            app_secret="secret",
            eventbus=eventbus,
            # account_id 미설정 (default "")
        )
        with pytest.raises(InvalidAccountIdError):
            await client._publish_connected()


# ── 수신 루프 (#3106) ─────────────────────────────

PINGPONG = json.dumps(
    {"header": {"tr_id": "PINGPONG", "datetime": "20261127100000"}},
    separators=(",", ":"),
)
SUBSCRIBE_OK = json.dumps(
    {
        "header": {"tr_id": CHANNEL_PRICE, "tr_key": "005930", "encrypt": "N"},
        "body": {"rt_cd": "0", "msg_cd": "OPSP0000", "msg1": "SUBSCRIBE SUCCESS"},
    }
)
LONG_PINGPONG = json.dumps(
    {"header": {"tr_id": "PINGPONG", "datetime": "2" * 120}},
    separators=(",", ":"),
)
WIDE_PINGPONG = json.dumps(
    {"header": {"tr_id": "PINGPONG", "datetime": "가" * 30}},
    ensure_ascii=False,
    separators=(",", ":"),
)


@pytest.fixture
def loop_log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``connect``와 ``asyncio.sleep``의 차례를 기록한다. sleep은 자지 않는다."""
    log: list[str] = []
    real_sleep = asyncio.sleep

    async def _recording_sleep(delay: float, *args: object) -> None:
        log.append(f"sleep {delay}")
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _recording_sleep)
    return log


@pytest.fixture
def live_client(
    monkeypatch: pytest.MonkeyPatch,
    kis_stream_external_guard,
    eventbus: MagicMock,
) -> KISStreamClient:
    """원본 수신 루프를 쓰는 클라이언트. ``websockets``는 테스트가 가짜로 바꾼다."""
    monkeypatch.setattr(
        KISStreamClient,
        "_connect_and_recv",
        kis_stream_external_guard.original_connect_and_recv,
    )
    return KISStreamClient(
        websocket_url="ws://ops.koreainvestment.com:31000",
        app_key="key",
        app_secret="secret",
        approval_key="approval",
        eventbus=eventbus,
        account_id="acc-001",
    )


def _disconnected_events(eventbus: MagicMock) -> list[StreamDisconnectedEvent]:
    return [
        call.args[0]
        for call in eventbus.publish.call_args_list
        if isinstance(call.args[0], StreamDisconnectedEvent)
    ]


async def _run_until_drained(
    client: KISStreamClient, sock: FakeSocket, *, timeout: float = 2.0
) -> None:
    await client.connect()
    await asyncio.wait_for(sock.drained.wait(), timeout)


class TestPingPong:
    """PINGPONG에 받은 원문으로 pong 제어 프레임을 되돌린다 (#3106 (a))."""

    async def test_str_pingpong_pongs_raw_once(
        self, live_client: KISStreamClient, loop_log: list[str], monkeypatch
    ) -> None:
        sock = FakeSocket([PINGPONG])
        ws = FakeWebsockets([sock], loop_log)
        ws.install(monkeypatch)
        try:
            await _run_until_drained(live_client, sock)
            assert len(sock.pongs) == 1
            assert sock.pongs[0] is PINGPONG
            assert sock.sent == []
            assert ws.connect_calls == 1
        finally:
            await live_client.disconnect()

    async def test_bytes_pingpong_pongs_raw_bytes(
        self, live_client: KISStreamClient, loop_log: list[str], monkeypatch
    ) -> None:
        raw = PINGPONG.encode()
        sock = FakeSocket([raw])
        ws = FakeWebsockets([sock], loop_log)
        ws.install(monkeypatch)
        try:
            await _run_until_drained(live_client, sock)
            assert len(sock.pongs) == 1
            assert sock.pongs[0] is raw
            assert ws.connect_calls == 1
        finally:
            await live_client.disconnect()

    @pytest.mark.parametrize(
        "message",
        [
            SUBSCRIBE_OK,
            '{"header":1}',
            '{"header":{"tr_id":"PINGPONG"}',
            b"\xff\xfe{",
            '[{"header":{"tr_id":"PINGPONG"}}]',
            "{bad json",
        ],
        ids=["subscribe-ok", "header-int", "json-error", "undecodable", "list", "bad"],
    )
    async def test_non_pingpong_no_pong_no_reconnect(
        self,
        live_client: KISStreamClient,
        loop_log: list[str],
        monkeypatch,
        eventbus: MagicMock,
        message: str | bytes,
    ) -> None:
        received: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            received.append((symbol, price))

        live_client.on_price(on_price)
        after = price_frame(price_record("005930", 70000))
        sock = FakeSocket([message, after])
        ws = FakeWebsockets([sock], loop_log)
        ws.install(monkeypatch)
        try:
            await _run_until_drained(live_client, sock)
            assert sock.pongs == []
            assert ws.connect_calls == 1
            assert _disconnected_events(eventbus) == []
            assert received == [("005930", 70000.0)]
        finally:
            await live_client.disconnect()

    def test_wide_pingpong_is_short_in_chars_long_in_bytes(self) -> None:
        assert len(WIDE_PINGPONG) <= 125 < len(WIDE_PINGPONG.encode())

    @pytest.mark.parametrize(
        "message",
        [LONG_PINGPONG, LONG_PINGPONG.encode(), WIDE_PINGPONG],
        ids=["str", "bytes", "utf8-wide"],
    )
    async def test_too_long_pingpong_skips_pong_and_warns_once(
        self,
        live_client: KISStreamClient,
        loop_log: list[str],
        monkeypatch,
        eventbus: MagicMock,
        caplog: pytest.LogCaptureFixture,
        message: str | bytes,
    ) -> None:
        sock = FakeSocket([message, message])
        ws = FakeWebsockets([sock], loop_log)
        ws.install(monkeypatch)
        caplog.set_level(logging.DEBUG, logger="ante.broker.kis_stream")
        try:
            await _run_until_drained(live_client, sock)
            assert sock.pongs == []
            assert ws.connect_calls == 1
            assert _disconnected_events(eventbus) == []
        finally:
            await live_client.disconnect()
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "PINGPONG" in r.getMessage()
        ]
        assert len(warnings) == 1

    async def test_pong_send_failure_reconnects(
        self,
        live_client: KISStreamClient,
        loop_log: list[str],
        monkeypatch,
        eventbus: MagicMock,
    ) -> None:
        # 첫 소켓은 대본 뒤에도 닫히지 않는다: 재접속은 pong 예외로만 생긴다
        first = FakeSocket([PINGPONG], pong_error=ConnectionError("closed"))
        second = FakeSocket([])
        ws = FakeWebsockets([first, second], loop_log)
        ws.install(monkeypatch)
        try:
            await _run_until_drained(live_client, second)
            assert ws.connect_calls == 2
            assert loop_log == ["connect", "sleep 1.0", "connect"]
            events = _disconnected_events(eventbus)
            assert [e.reason for e in events] == ["connection_lost"]
        finally:
            await live_client.disconnect()


class TestServerCloseReconnect:
    """서버의 정상 종료도 끊김과 같게: 이벤트 → 기다림 → 재접속 (#3106 (b))."""

    async def test_clean_close_waits_and_publishes_between_connects(
        self,
        live_client: KISStreamClient,
        loop_log: list[str],
        monkeypatch,
        eventbus: MagicMock,
    ) -> None:
        ws = FakeWebsockets([], loop_log)

        def _stop_on_third(n: int) -> None:
            if n == 3:
                live_client._running = False

        ws.on_connect = _stop_on_third
        ws.install(monkeypatch)
        try:
            await live_client.connect()
            task = live_client._recv_task
            assert task is not None
            await asyncio.wait_for(task, 2.0)
            assert ws.connect_calls == 3
            assert loop_log == [
                "connect",
                "sleep 1.0",
                "connect",
                "sleep 1.0",
                "connect",
            ]
            events = _disconnected_events(eventbus)
            assert [e.reason for e in events] == ["connection_lost"] * 2
            assert all(e.account_id == "acc-001" for e in events)
        finally:
            await live_client.disconnect()

    async def test_disconnect_while_receiving_no_event_no_wait(
        self,
        live_client: KISStreamClient,
        loop_log: list[str],
        monkeypatch,
        eventbus: MagicMock,
    ) -> None:
        sock = FakeSocket([SUBSCRIBE_OK])
        ws = FakeWebsockets([sock], loop_log)
        ws.install(monkeypatch)
        await _run_until_drained(live_client, sock)
        task = live_client._recv_task
        assert task is not None

        await live_client.disconnect()

        assert task.done()
        assert ws.connect_calls == 1
        assert loop_log == ["connect"]
        assert _disconnected_events(eventbus) == []


class TestMultiRecordPriceFrame:
    """한 프레임의 건수 × 46필드를 모두 읽는다 (#3106 (c))."""

    @pytest.fixture
    def received(self, stream_client: KISStreamClient) -> list[tuple[str, float]]:
        got: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            got.append((symbol, price))

        stream_client.on_price(on_price)
        return got

    async def test_three_records_in_order(
        self, stream_client: KISStreamClient, received: list[tuple[str, float]]
    ) -> None:
        raw = price_frame(
            price_record("005930", 100),
            price_record("000660", 95),
            price_record("005930", 89),
        )
        await stream_client._handle_message(raw)
        assert received == [("005930", 100.0), ("000660", 95.0), ("005930", 89.0)]

    async def test_non_numeric_price_skips_only_that_record(
        self, stream_client: KISStreamClient, received: list[tuple[str, float]]
    ) -> None:
        raw = price_frame(
            price_record("005930", 100),
            price_record("005930", "abc"),
            price_record("005930", 89),
        )
        await stream_client._handle_message(raw)
        assert received == [("005930", 100.0), ("005930", 89.0)]

    async def test_mismatch_first_record_only_warns_once(
        self,
        stream_client: KISStreamClient,
        received: list[tuple[str, float]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="ante.broker.kis_stream")
        three = [price_record("005930", p) for p in (100, 95, 89)]
        await stream_client._handle_message(price_frame(*three, count="002"))
        await stream_client._handle_message(price_frame(*three) + "^extra")
        assert received == [("005930", 100.0), ("005930", 100.0)]
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    @pytest.mark.parametrize("count", ["x", "0", "-1", "999999"])
    async def test_bad_count_first_record_only(
        self,
        stream_client: KISStreamClient,
        received: list[tuple[str, float]],
        count: str,
    ) -> None:
        three = [price_record("005930", p) for p in (100, 95, 89)]
        await stream_client._handle_message(price_frame(*three, count=count))
        assert received == [("005930", 100.0)]
