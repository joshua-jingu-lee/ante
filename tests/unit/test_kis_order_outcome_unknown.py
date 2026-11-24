"""매수·매도 주문은 접수 여부를 알 수 없는 실패에서 다시 보내지 않는다 (#2911).

가짜 세션을 ``adapter._session`` 에 넣어 ``_send_http`` → ``_handle_response`` 를
실제로 지나게 한다. 실제 외부 API는 부르지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import aiohttp
import pytest
import yarl
from aiohttp.client_reqrep import ConnectionKey
from multidict import CIMultiDict, CIMultiDictProxy

import ante.broker.kis as kis_module
from ante.broker.exceptions import APIError
from ante.broker.kis import KISDomesticAdapter

UNKNOWN = "order_outcome_unknown"
NEW_ORDER_TRS = ("VTTC0012U", "TTTC0012U", "VTTC0011U", "TTTC0011U")
CANCEL_TR = "VTTC0013U"
QUERY_TR = "FHKST01010100"
URL = "https://example.invalid/uapi/domestic-stock/v1/trading/order-cash"
MAX_ORDER = kis_module.DEFAULT_MAX_RETRIES_ORDER
MAX_QUERY = kis_module.DEFAULT_MAX_RETRIES_QUERY

_HTML = "<html>"
_SUCCESS = json.dumps(
    {"rt_cd": "0", "output": {"ODNO": "0000001", "KRX_FWDG_ORD_ORGNO": "00950"}}
)


class _Resp:
    """상태·본문·json 동작을 정한 가짜 응답."""

    def __init__(
        self,
        status: int,
        body: str = "",
        json_error: Callable[[], Exception] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._json_error = json_error
        self.headers: dict[str, str] = {}

    async def text(self) -> str:
        return self._body

    async def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error()
        return json.loads(self._body)


Outcome = Callable[[], Any]


class _Ctx:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    async def __aenter__(self) -> _Resp:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome  # type: ignore[no-any-return]

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Session:
    """전송마다 각본의 다음 결과를 돌려준다(각본이 끝나면 마지막 결과를 반복)."""

    def __init__(self, script: list[Outcome]) -> None:
        self._script = list(script)
        self.sent_tr_ids: list[str] = []

    def _next(self, headers: dict[str, str]) -> _Ctx:
        self.sent_tr_ids.append(headers.get("tr_id", ""))
        factory = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        return _Ctx(factory())

    def post(self, url: str, headers: dict[str, str], json: Any = None) -> _Ctx:
        return self._next(headers)

    def get(self, url: str, headers: dict[str, str], params: Any = None) -> _Ctx:
        return self._next(headers)

    @property
    def sends(self) -> int:
        return len(self.sent_tr_ids)


def _make(script: list[Outcome], *, is_paper: bool = True) -> tuple[Any, _Session]:
    adapter = KISDomesticAdapter(
        config={
            "app_key": "fake-key",
            "app_secret": "fake-secret",
            "account_no": "0000000001",
            "is_paper": is_paper,
        }
    )

    async def _noop() -> None:
        return None

    adapter._ensure_authenticated = _noop  # type: ignore[method-assign]
    adapter._rate_limit_wait = _noop  # type: ignore[method-assign]
    adapter._retry_handler._backoff_base = 0.0
    session = _Session(script)
    adapter._session = session
    return adapter, session


def _raise(exc_factory: Callable[[], BaseException]) -> Outcome:
    return exc_factory


def _status(status: int, body: str = "") -> Outcome:
    return lambda: _Resp(status, body)


def _kis_body(msg_cd: str) -> str:
    return json.dumps({"rt_cd": "1", "msg_cd": msg_cd, "msg1": "fake"})


def _connector_error() -> BaseException:
    key = ConnectionKey("example.invalid", 443, True, True, None, None, None)
    return aiohttp.ClientConnectorError(key, OSError(111, "fake refused"))


def _content_type_error() -> BaseException:
    url = yarl.URL(URL)
    info = aiohttp.RequestInfo(url, "POST", CIMultiDictProxy(CIMultiDict()), url)
    return aiohttp.ContentTypeError(info, (), message="fake content type")


def _json_decode_error() -> BaseException:
    return json.JSONDecodeError("fake", "<html>", 0)


async def _send(adapter: Any, tr_id: str) -> Any:
    method = "GET" if tr_id == QUERY_TR else "POST"
    return await adapter._request_with_cont(
        method, URL, tr_id, json_data={"fake": "order"}
    )


_UNKNOWN_RECORDED: list[tuple[str, Outcome, int]] = [
    ("timeout", _raise(lambda: TimeoutError()), 0),
    ("conn_reset", _raise(lambda: ConnectionResetError("fake reset")), 0),
    ("oserror", _raise(lambda: OSError("fake os")), 0),
    ("aiohttp_server_timeout", _raise(lambda: aiohttp.ServerTimeoutError()), 0),
    ("aiohttp_client_os", _raise(lambda: aiohttp.ClientOSError(104, "fake")), 0),
    ("aiohttp_connector", _raise(_connector_error), 0),
    ("500_empty", _status(500, ""), 500),
    ("502_plain", _status(502, "Bad Gateway"), 502),
    ("503_rt_cd_0", _status(503, json.dumps({"rt_cd": "0"})), 503),
    ("500_unregistered", _status(500, _kis_body("ZZZZ9999")), 500),
]

_UNKNOWN_NOT_RECORDED: list[tuple[str, Outcome, int]] = [
    ("504_empty", _status(504, ""), 504),
    ("504_unregistered", _status(504, _kis_body("ZZZZ9999")), 504),
    ("200_json_decode", lambda: _Resp(200, _HTML, _json_decode_error), 0),
    ("200_content_type", lambda: _Resp(200, _HTML, _content_type_error), 0),
    (
        "server_disconnected",
        _raise(lambda: aiohttp.ServerDisconnectedError()),
        0,
    ),
    ("payload_error", _raise(lambda: aiohttp.ClientPayloadError("fake")), 0),
]


class TestNewOrderUnknownOutcome:
    @pytest.mark.parametrize("tr_id", NEW_ORDER_TRS)
    @pytest.mark.parametrize(
        ("case", "outcome", "status"),
        _UNKNOWN_RECORDED,
        ids=[c[0] for c in _UNKNOWN_RECORDED],
    )
    async def test_unknown_failure_sends_once_and_records_once(
        self, tr_id: str, case: str, outcome: Outcome, status: int
    ) -> None:
        adapter, session = _make([outcome])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, tr_id)

        assert session.sends == 1
        assert exc_info.value.error_code == UNKNOWN
        assert exc_info.value.retryable is False
        assert exc_info.value.status_code == status
        assert adapter.circuit_breaker.failure_count == 1

    @pytest.mark.parametrize("tr_id", NEW_ORDER_TRS)
    @pytest.mark.parametrize(
        ("case", "outcome", "status"),
        _UNKNOWN_NOT_RECORDED,
        ids=[c[0] for c in _UNKNOWN_NOT_RECORDED],
    )
    async def test_unknown_failure_not_recorded_in_breaker(
        self, tr_id: str, case: str, outcome: Outcome, status: int
    ) -> None:
        adapter, session = _make([outcome])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, tr_id)

        assert session.sends == 1
        assert exc_info.value.error_code == UNKNOWN
        assert exc_info.value.retryable is False
        assert exc_info.value.status_code == status
        assert adapter.circuit_breaker.failure_count == 0

    async def test_rate_limited_then_timeout_stops_at_timeout(self) -> None:
        adapter, session = _make([_status(429, ""), _raise(lambda: TimeoutError())])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, "VTTC0012U")

        assert session.sends == 2
        assert exc_info.value.error_code == UNKNOWN

    async def test_message_names_the_unknown_outcome_and_cause(self) -> None:
        adapter, _ = _make([_status(503, "busy")])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, "TTTC0011U")

        message = str(exc_info.value)
        assert "주문 접수 여부 미상" in message
        assert "HTTP 503" in message
        assert isinstance(exc_info.value.__cause__, APIError)


_CLEAR_REJECTIONS: list[tuple[str, Outcome]] = [
    ("429", _status(429, "")),
    ("500_EGW00201", _status(500, _kis_body("EGW00201"))),
    ("500_EGW00133", _status(500, _kis_body("EGW00133"))),
    ("200_APBK0600", _status(200, _kis_body("APBK0600"))),
    ("200_unregistered", _status(200, _kis_body("ZZZZ9999"))),
]


class TestNewOrderClearRejectionStillRetries:
    @pytest.mark.parametrize("tr_id", NEW_ORDER_TRS)
    @pytest.mark.parametrize(
        ("case", "outcome"), _CLEAR_REJECTIONS, ids=[c[0] for c in _CLEAR_REJECTIONS]
    )
    async def test_persistent_rejection_retries_to_limit(
        self, tr_id: str, case: str, outcome: Outcome
    ) -> None:
        adapter, session = _make([outcome])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, tr_id)

        assert session.sends == MAX_ORDER + 1
        assert exc_info.value.error_code != UNKNOWN

    @pytest.mark.parametrize(
        ("case", "outcome"), _CLEAR_REJECTIONS, ids=[c[0] for c in _CLEAR_REJECTIONS]
    )
    async def test_rejection_then_success_sends_twice(
        self, case: str, outcome: Outcome
    ) -> None:
        adapter, session = _make([outcome, _status(200, _SUCCESS)])

        body, _ = await _send(adapter, "VTTC0012U")

        assert body["rt_cd"] == "0"
        assert session.sends == 2


_REGISTERED_FAILURES: list[tuple[str, Outcome, str]] = [
    ("200_APBK0919", _status(200, _kis_body("APBK0919")), "APBK0919"),
    ("500_APBK0919", _status(500, _kis_body("APBK0919")), "APBK0919"),
    ("504_EGW00201", _status(504, _kis_body("EGW00201")), "EGW00201"),
]


@pytest.mark.parametrize("tr_id", NEW_ORDER_TRS)
@pytest.mark.parametrize(
    ("case", "outcome", "code"),
    _REGISTERED_FAILURES,
    ids=[c[0] for c in _REGISTERED_FAILURES],
)
async def test_registered_code_failure_is_plain_failure(
    tr_id: str, case: str, outcome: Outcome, code: str
) -> None:
    adapter, session = _make([outcome])

    with pytest.raises(APIError) as exc_info:
        await _send(adapter, tr_id)

    assert session.sends == 1
    assert exc_info.value.error_code == code


class TestOtherTrsUnchanged:
    @pytest.mark.parametrize(
        ("tr_id", "max_retries"), [(CANCEL_TR, MAX_ORDER), (QUERY_TR, MAX_QUERY)]
    )
    @pytest.mark.parametrize(
        "outcome",
        [
            _raise(lambda: TimeoutError()),
            _status(503, ""),
            _status(500, _kis_body("ZZZZ9999")),
        ],
        ids=["timeout", "503", "500_unregistered"],
    )
    async def test_retries_as_before(
        self, tr_id: str, max_retries: int, outcome: Outcome
    ) -> None:
        adapter, session = _make([outcome])

        with pytest.raises(APIError) as exc_info:
            await _send(adapter, tr_id)

        assert session.sends == max_retries + 1
        assert exc_info.value.error_code != UNKNOWN

    @pytest.mark.parametrize("tr_id", [CANCEL_TR, QUERY_TR])
    @pytest.mark.parametrize(
        ("outcome", "exc_type"),
        [
            (_status(504, ""), APIError),
            (lambda: _Resp(200, _HTML, _json_decode_error), json.JSONDecodeError),
            (
                lambda: _Resp(200, _HTML, _content_type_error),
                aiohttp.ContentTypeError,
            ),
            (
                _raise(lambda: aiohttp.ServerDisconnectedError()),
                aiohttp.ServerDisconnectedError,
            ),
        ],
        ids=["504", "200_json_decode", "200_content_type", "server_disconnected"],
    )
    async def test_non_retryable_failure_raises_original_once(
        self, tr_id: str, outcome: Outcome, exc_type: type[BaseException]
    ) -> None:
        adapter, session = _make([outcome])

        with pytest.raises(exc_type) as exc_info:
            await _send(adapter, tr_id)

        assert session.sends == 1
        assert getattr(exc_info.value, "error_code", "") != UNKNOWN


class TestPublicPath:
    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_place_order_timeout_sends_once(self, side: str) -> None:
        adapter, session = _make([_raise(lambda: TimeoutError())])

        with pytest.raises(APIError) as exc_info:
            await adapter.place_order("005930", side, 1)

        assert session.sends == 1
        assert exc_info.value.error_code == UNKNOWN


async def test_new_order_tr_set_matches_place_order() -> None:
    chosen: set[str] = set()
    for is_paper in (True, False):
        for side in ("buy", "sell"):
            adapter, session = _make([_status(200, _SUCCESS)], is_paper=is_paper)
            await adapter.place_order("005930", side, 1)
            chosen.update(session.sent_tr_ids)

    new_order_trs = kis_module._NEW_ORDER_TR_IDS
    assert new_order_trs == chosen == set(NEW_ORDER_TRS)
    assert new_order_trs < kis_module._ORDER_TR_IDS
    assert "VTTC0013U" not in new_order_trs
    assert "TTTC0013U" not in new_order_trs
