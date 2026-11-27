"""텔레그램 요청 실패 로그의 봇 토큰 가림 테스트 (#3126).

재현은 127.0.0.1의 로컬 aiohttp 서버와 가짜 세션으로만 한다. 외부 접속은 없다.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import web

import ante.notification.telegram as telegram_mod
from ante.core.log.formatter import JsonFormatter
from ante.notification.base import NotificationLevel
from ante.notification.telegram import (
    TELEGRAM_SECRET_ATTR,
    TelegramAdapter,
    TelegramLogRedactFilter,
    describe_telegram_error,
)
from ante.notification.telegram_receiver import TelegramCommandReceiver

_TOKEN = "123456:SECRET-TOKEN-VALUE"
_CHAT_ID = "-100987654321"
_REPLY_CHAT_ID = 55667788
_TITLE = "거래 상태 변경 (킬 스위치)"

_SITES = ("send_message", "answer_callback_query", "get_updates", "reply")
_SITE_LOGGER = {
    "send_message": "ante.notification.telegram",
    "answer_callback_query": "ante.notification.telegram",
    "get_updates": "ante.notification.telegram_receiver",
    "reply": "ante.notification.telegram_receiver",
}


def _forbidden() -> list[str]:
    return [_TOKEN, quote(_TOKEN, safe=""), _TOKEN.replace(":", "%3a")]


async def _call_site(site: str, adapter: TelegramAdapter) -> None:
    receiver = TelegramCommandReceiver(adapter=adapter, allowed_user_ids=[1])
    if site == "send_message":
        assert (
            await adapter.send_rich(NotificationLevel.CRITICAL, _TITLE, "본문") is False
        )
    elif site == "answer_callback_query":
        assert await adapter.answer_callback_query("cb-1", "확인") is False
    elif site == "get_updates":
        assert await receiver._get_updates() == []
    else:
        await receiver._reply(_REPLY_CHAT_ID, "회신")


def _site_records(
    caplog: pytest.LogCaptureFixture, site: str
) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == _SITE_LOGGER[site] and r.levelno >= logging.WARNING
    ]


def _assert_redacted(caplog: pytest.LogCaptureFixture, site: str) -> str:
    records = _site_records(caplog, site)
    assert records, f"{site}: 실패 로그가 찍히지 않았다"
    text = caplog.text
    for secret in _forbidden():
        assert secret not in text, f"{site}: {secret!r} in {text!r}"
    for record in records:
        assert record.exc_info is None, site
    return "\n".join(r.getMessage() for r in records)


# ── 로컬 서버: 리다이렉트 반복 · JSON이 아닌 200 ─────────────────


@pytest.fixture
async def local_server() -> AsyncIterator[Callable[[str], Awaitable[int]]]:
    runners: list[web.AppRunner] = []

    async def start(mode: str) -> int:
        async def handler(request: web.Request) -> web.Response:
            if mode == "redirect":
                raise web.HTTPFound(location=request.path_qs)
            return web.Response(text="<html>oops</html>", content_type="text/html")

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        server = site._server
        assert server is not None
        return int(server.sockets[0].getsockname()[1])  # type: ignore[union-attr]

    yield start
    for runner in runners:
        await runner.cleanup()


def _local_adapter(port: int) -> TelegramAdapter:
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    adapter._api_base = f"http://127.0.0.1:{port}/bot{_TOKEN}"
    return adapter


@pytest.mark.parametrize("site", _SITES)
async def test_redirect_loop_does_not_log_token(site, local_server, caplog):
    port = await local_server("redirect")
    adapter = _local_adapter(port)

    with caplog.at_level(logging.DEBUG):
        await asyncio.wait_for(_call_site(site, adapter), 10)

    messages = _assert_redacted(caplog, site)
    assert "TooManyRedirects" in messages
    if site == "send_message":
        assert _TITLE in messages


async def test_get_updates_non_json_200_does_not_log_token(local_server, caplog):
    port = await local_server("html")
    adapter = _local_adapter(port)

    with caplog.at_level(logging.DEBUG):
        await asyncio.wait_for(_call_site("get_updates", adapter), 10)

    messages = _assert_redacted(caplog, "get_updates")
    assert "ContentTypeError" in messages
    assert "200" in messages
    assert "/getUpdates" in messages


# ── 가짜 세션: 예외 종류를 열거하지 않는 불변식 ─────────────────


class _RaisingSession:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __aenter__(self) -> _RaisingSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> Any:
        raise self._exc

    def get(self, url: str, params: dict[str, Any]) -> Any:
        raise self._exc


def _with_url(adapter: TelegramAdapter) -> BaseException:
    return RuntimeError(f"boom url={adapter._api_base}/x?k=1")


def _token_only(adapter: TelegramAdapter) -> BaseException:
    return RuntimeError(f"boom token={_TOKEN} end")


@pytest.mark.parametrize("make_exc", [_with_url, _token_only])
@pytest.mark.parametrize("site", _SITES)
async def test_any_exception_does_not_log_token(site, make_exc, caplog):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    exc = make_exc(adapter)

    with (
        patch("aiohttp.ClientSession", side_effect=lambda **_: _RaisingSession(exc)),
        caplog.at_level(logging.DEBUG),
    ):
        await _call_site(site, adapter)

    messages = _assert_redacted(caplog, site)
    assert "RuntimeError" in messages
    assert "boom" in messages


# ── 가림 도우미 ─────────────────────────────────


def test_describe_masks_bot_path_and_keeps_diagnostics():
    exc = aiohttp.ClientError(
        f"404, message='Not Found', url='https://api.telegram.org/bot{_TOKEN}/sendMessage'"
    )

    out = describe_telegram_error(exc, _TOKEN)

    assert _TOKEN not in out
    assert out.startswith("ClientError: 404")
    assert "/bot***/sendMessage" in out


def test_describe_masks_token_without_url_shape():
    out = describe_telegram_error(RuntimeError(f"token {_TOKEN} leaked"), _TOKEN)

    assert out == "RuntimeError: token *** leaked"


@pytest.mark.parametrize(
    "encoded", [quote(_TOKEN, safe=""), _TOKEN.replace(":", "%3a")]
)
def test_describe_masks_url_encoded_token(encoded):
    exc = RuntimeError(f"url=https://api.telegram.org/bot{encoded}/getUpdates?x=1")

    out = describe_telegram_error(exc, _TOKEN)

    assert encoded not in out
    assert "/bot***/getUpdates?x=1" in out


@pytest.mark.parametrize(
    "encoded", [quote(_TOKEN, safe=""), _TOKEN.replace(":", "%3a")]
)
def test_describe_masks_url_encoded_token_without_url_shape(encoded):

    out = describe_telegram_error(RuntimeError(f"key={encoded}"), _TOKEN)

    assert encoded not in out


def test_describe_empty_message_returns_type_only():
    assert describe_telegram_error(TimeoutError(), _TOKEN) == "TimeoutError"


def test_describe_empty_token_leaves_message_unchanged():
    assert describe_telegram_error(RuntimeError("plain text"), "") == (
        "RuntimeError: plain text"
    )


# ── 로거 가림 필터 ─────────────────────────────────


_RECEIVER_SITES = ("get_updates", "reply")


@pytest.mark.parametrize("make_exc", [_with_url, _token_only])
@pytest.mark.parametrize("site", _RECEIVER_SITES)
async def test_receiver_sites_keep_redacted_traceback(site, make_exc, caplog):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    exc = make_exc(adapter)

    with (
        patch("aiohttp.ClientSession", side_effect=lambda **_: _RaisingSession(exc)),
        caplog.at_level(logging.DEBUG),
    ):
        await _call_site(site, adapter)

    _assert_redacted(caplog, site)
    (record,) = _site_records(caplog, site)
    assert record.exc_text is not None
    assert "Traceback" in record.exc_text
    assert "RuntimeError: boom" in record.exc_text
    assert TELEGRAM_SECRET_ATTR not in record.__dict__


@pytest.mark.parametrize("make_exc", [_with_url, _token_only])
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("formatter_kind", ["json", "standard"])
async def test_formatted_output_has_no_token(site, make_exc, formatter_kind):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    exc = make_exc(adapter)
    formatter: logging.Formatter = (
        JsonFormatter() if formatter_kind == "json" else logging.Formatter()
    )
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    target = logging.getLogger(_SITE_LOGGER[site])
    target.addHandler(handler)
    try:
        with patch(
            "aiohttp.ClientSession", side_effect=lambda **_: _RaisingSession(exc)
        ):
            await _call_site(site, adapter)
    finally:
        target.removeHandler(handler)

    output = stream.getvalue()
    assert "RuntimeError" in output, output
    for secret in _forbidden():
        assert secret not in output, output
    if formatter_kind == "json":
        lines = [json.loads(line) for line in output.splitlines()]
        assert lines and all("exc" not in line for line in lines)
        assert all(TELEGRAM_SECRET_ATTR not in json.dumps(line) for line in lines)
    elif site in _RECEIVER_SITES:
        assert "Traceback (most recent call last)" in output


class _ExplodingStr:
    def __str__(self) -> str:
        raise RuntimeError(f"str failed /bot{_TOKEN}/x")


@pytest.mark.parametrize(
    "args", [("not-a-number",), (_ExplodingStr(),)], ids=["bad-format", "bad-str"]
)
@pytest.mark.parametrize("site", ["send_message", "get_updates"])
def test_filter_failure_does_not_escape_logging_call(site, args, caplog):
    target = logging.getLogger(_SITE_LOGGER[site])
    fmt = "%d" if args[0] == "not-a-number" else "%s"

    with caplog.at_level(logging.DEBUG):
        try:
            raise RuntimeError(f"inner {_TOKEN}")
        except RuntimeError:
            target.warning(fmt, *args, exc_info=True)

    (record,) = [r for r in caplog.records if r.name == target.name]
    assert record.getMessage() == telegram_mod._FILTER_FAILURE_MESSAGE
    assert record.exc_info is None
    assert record.exc_text is None
    assert _TOKEN not in caplog.text


def test_both_telegram_loggers_carry_the_filter():
    for name in set(_SITE_LOGGER.values()):
        filters = logging.getLogger(name).filters
        assert any(isinstance(f, TelegramLogRedactFilter) for f in filters), name


@pytest.mark.parametrize("site", _RECEIVER_SITES)
def test_record_without_secret_keeps_exception_fields(site):
    target = logging.getLogger(_SITE_LOGGER[site])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    target.addHandler(handler)
    try:
        try:
            raise RuntimeError("작업 실패: 비밀 없음")
        except RuntimeError:
            target.exception("텔레그램 작업 실행 실패: %s", "job-1")
    finally:
        target.removeHandler(handler)

    (line,) = [json.loads(x) for x in stream.getvalue().splitlines()]
    assert line["msg"] == "텔레그램 작업 실행 실패: job-1"
    assert line["exc"]["type"] == "RuntimeError"
    assert line["exc"]["message"] == "작업 실패: 비밀 없음"
    assert "Traceback" in line["exc"]["traceback"]
    assert line["exc"]["fingerprint"]


def test_secret_only_in_message_keeps_exception_fields(caplog):
    target = logging.getLogger(_SITE_LOGGER["reply"])

    with caplog.at_level(logging.DEBUG):
        try:
            raise RuntimeError("비밀 없음")
        except RuntimeError:
            target.warning("주소 %s", f"/bot{_TOKEN}/x", exc_info=True)

    (record,) = [r for r in caplog.records if r.name == target.name]
    assert record.exc_info is not None
    assert _TOKEN not in caplog.text
    assert "/bot***/x" in record.getMessage()


def test_fake_token_has_bot_token_shape():
    assert re.fullmatch(r"\d+:[A-Za-z0-9_-]+", _TOKEN)


@pytest.mark.parametrize(
    "encoded", [_TOKEN, quote(_TOKEN, safe=""), _TOKEN.replace(":", "%3a")]
)
def test_regex_masks_url_shaped_token_without_known_token(encoded):
    exc = RuntimeError(f"url=https://api.telegram.org/bot{encoded}/getUpdates")

    out = describe_telegram_error(exc, "")

    assert out == "RuntimeError: url=https://api.telegram.org/bot***/getUpdates"


@pytest.mark.parametrize("word", ["/bots", "/botfather", "/bot", "/bot123", "/bot:x"])
def test_non_token_bot_words_are_unchanged(word):
    exc = ValueError(f"unknown command {word} here")

    assert describe_telegram_error(exc, _TOKEN) == (
        f"ValueError: unknown command {word} here"
    )


@pytest.mark.parametrize("site", _RECEIVER_SITES)
def test_bots_command_record_is_unchanged(site, caplog):
    target = logging.getLogger(_SITE_LOGGER[site])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    target.addHandler(handler)
    try:
        with caplog.at_level(logging.DEBUG):
            target.info("텔레그램 명령: text=%s", "/bots")
            try:
                raise ValueError("unknown command /bots")
            except ValueError:
                target.exception("명령 처리 실패: %s", "/bots")
    finally:
        target.removeHandler(handler)

    info, failure = [r for r in caplog.records if r.name == target.name]
    assert (info.msg, info.args) == ("텔레그램 명령: text=%s", ("/bots",))
    assert failure.exc_info is not None
    lines = [json.loads(x) for x in stream.getvalue().splitlines()]
    assert [line["msg"] for line in lines] == [
        "텔레그램 명령: text=/bots",
        "명령 처리 실패: /bots",
    ]
    exc = lines[1]["exc"]
    assert exc["message"] == "unknown command /bots"
    assert exc["fingerprint"]
    assert "Traceback" in exc["traceback"]
