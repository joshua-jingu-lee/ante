"""텔레그램 HTTP 요청의 전체 시간 제한 테스트 (#3110).

실제 시간 초과는 127.0.0.1의 로컬 서버(연결을 받고 응답하지 않는다)로 잠근다.
외부 접속은 없다.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest

import ante.notification.telegram as telegram_mod
import ante.notification.telegram_receiver as receiver_mod
from ante.notification.base import NotificationLevel
from ante.notification.telegram import TelegramAdapter
from ante.notification.telegram_receiver import TelegramCommandReceiver

_TOKEN = "123456:SECRET-TOKEN-VALUE"
_CHAT_ID = "-100987654321"
_REPLY_CHAT_ID = 55667788
_NOTIFICATION_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "ante" / "notification"
)


# ── 기록용 가짜 세션 ─────────────────────────────────


class _FakeResponse:
    status = 200

    async def json(self) -> dict[str, Any]:
        return {"ok": True, "result": []}

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _RecordingSession:
    def __init__(self, record: list[dict[str, Any]], **kwargs: Any) -> None:
        self._record = record
        self._entry: dict[str, Any] = {"session_kwargs": kwargs}
        record.append(self._entry)

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self._entry["method"] = "post"
        self._entry["url"] = url
        return _FakeResponse()

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        self._entry["method"] = "get"
        self._entry["url"] = url
        self._entry["params"] = params
        return _FakeResponse()


@pytest.fixture
def recorded_sessions():
    record: list[dict[str, Any]] = []

    def factory(*args: Any, **kwargs: Any) -> _RecordingSession:
        assert not args
        return _RecordingSession(record, **kwargs)

    with patch("aiohttp.ClientSession", side_effect=factory):
        yield record


def _assert_total_timeout(entry: dict[str, Any]) -> None:
    timeout = entry["session_kwargs"].get("timeout")
    assert isinstance(timeout, aiohttp.ClientTimeout), entry
    assert timeout.total == telegram_mod.TELEGRAM_REQUEST_TIMEOUT


# ── T1: 다섯 진입이 모두 세션 생성 때 전체 제한을 준다 ─────────


def test_constant_is_five_seconds():
    assert telegram_mod.TELEGRAM_REQUEST_TIMEOUT == 5.0
    assert (
        receiver_mod.TELEGRAM_REQUEST_TIMEOUT is telegram_mod.TELEGRAM_REQUEST_TIMEOUT
    )


async def test_adapter_entries_pass_total_timeout(recorded_sessions):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)

    assert await adapter.send(NotificationLevel.INFO, "본문")
    assert await adapter.send_rich(NotificationLevel.INFO, "제목", "본문")
    assert await adapter.send_with_buttons(
        NotificationLevel.INFO,
        "결재",
        [[{"text": "승인", "callback_data": "approve:x"}]],
    )
    assert await adapter.answer_callback_query("cb-1", "확인")

    assert len(recorded_sessions) == 4
    for entry in recorded_sessions:
        _assert_total_timeout(entry)


async def test_receiver_entries_pass_total_timeout(recorded_sessions):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    receiver = TelegramCommandReceiver(adapter=adapter, allowed_user_ids=[1])

    await receiver._reply(_REPLY_CHAT_ID, "회신")
    assert await receiver._get_updates() == []

    assert [e["method"] for e in recorded_sessions] == ["post", "get"]
    for entry in recorded_sessions:
        _assert_total_timeout(entry)


# ── T4: 롱폴링 대기가 전체 제한보다 작다 ─────────────────


async def test_long_poll_wait_is_shorter_than_total_timeout(recorded_sessions):
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    receiver = TelegramCommandReceiver(adapter=adapter, allowed_user_ids=[1])

    await receiver._get_updates()

    (entry,) = recorded_sessions
    long_poll = entry["params"]["timeout"]
    assert 0 < long_poll < telegram_mod.TELEGRAM_REQUEST_TIMEOUT


# ── T2: 응답하지 않는 로컬 서버에 대해 짧은 시간 안에 실패로 끝난다 ─────


@pytest.fixture
async def silent_server():
    """연결을 받고 요청을 읽은 뒤 응답하지 않는 127.0.0.1 서버의 포트."""
    writers: list[asyncio.StreamWriter] = []
    connections: list[int] = []

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        writers.append(writer)
        connections.append(1)
        try:
            await reader.read()
        except (ConnectionError, asyncio.CancelledError):
            pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, connections
    finally:
        for writer in writers:
            writer.close()
        server.close()
        await server.wait_closed()


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(telegram_mod, "TELEGRAM_REQUEST_TIMEOUT", 0.2)
    monkeypatch.setattr(receiver_mod, "TELEGRAM_REQUEST_TIMEOUT", 0.2)


def _silent_adapter(port: int) -> TelegramAdapter:
    adapter = TelegramAdapter(_TOKEN, _CHAT_ID)
    adapter._api_base = f"http://127.0.0.1:{port}/bot{_TOKEN}"
    return adapter


def _assert_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    for record in caplog.records:
        text = record.getMessage()
        assert _TOKEN not in text
        assert _CHAT_ID not in text
        assert str(_REPLY_CHAT_ID) not in text


async def test_send_rich_times_out_with_title_in_log(
    silent_server, short_timeout, caplog
):
    port, connections = silent_server
    adapter = _silent_adapter(port)
    title = "거래 상태 변경 (킬 스위치)"

    with caplog.at_level(logging.WARNING, logger="ante.notification.telegram"):
        result = await asyncio.wait_for(
            adapter.send_rich(NotificationLevel.CRITICAL, title, "본문 둘째 줄"),
            2,
        )

    assert result is False
    assert connections
    messages = [r.getMessage() for r in caplog.records]
    assert any("TimeoutError" in m and title in m for m in messages), messages
    assert all("본문 둘째 줄" not in m for m in messages)
    _assert_no_secret(caplog)


async def test_answer_callback_query_times_out(silent_server, short_timeout, caplog):
    port, connections = silent_server
    adapter = _silent_adapter(port)

    with caplog.at_level(logging.WARNING, logger="ante.notification.telegram"):
        result = await asyncio.wait_for(
            adapter.answer_callback_query("cb-1", "확인"), 2
        )

    assert result is False
    assert connections
    assert any("TimeoutError" in r.getMessage() for r in caplog.records)
    _assert_no_secret(caplog)


async def test_reply_times_out_with_warning(silent_server, short_timeout, caplog):
    port, connections = silent_server
    receiver = TelegramCommandReceiver(
        adapter=_silent_adapter(port), allowed_user_ids=[1]
    )

    with caplog.at_level(logging.WARNING, logger="ante.notification"):
        await asyncio.wait_for(receiver._reply(_REPLY_CHAT_ID, "회신"), 2)

    assert connections
    assert any("텔레그램 회신 오류" in r.getMessage() for r in caplog.records)
    _assert_no_secret(caplog)


async def test_get_updates_times_out_to_empty(silent_server, short_timeout):
    port, connections = silent_server
    receiver = TelegramCommandReceiver(
        adapter=_silent_adapter(port), allowed_user_ids=[1]
    )

    assert await asyncio.wait_for(receiver._get_updates(), 2) == []
    assert connections


async def test_reply_timeout_does_not_kill_poll_loop(silent_server, short_timeout):
    port, connections = silent_server
    receiver = TelegramCommandReceiver(
        adapter=_silent_adapter(port), allowed_user_ids=[1], polling_interval=0
    )
    update = {
        "update_id": 7,
        "message": {
            "text": "/help",
            "from": {"id": 1},
            "chat": {"id": _REPLY_CHAT_ID},
        },
    }
    calls: list[int] = []

    async def fake_get_updates() -> list[dict[str, Any]]:
        calls.append(1)
        if len(calls) == 1:
            return [update]
        receiver._running = False
        return []

    receiver._get_updates = fake_get_updates  # type: ignore[method-assign]
    receiver._running = True

    await asyncio.wait_for(receiver._poll_loop(), 2)

    assert len(calls) == 2
    assert connections


# ── T3: 알림 디렉터리의 모든 세션 생성이 그 상수의 전체 제한을 준다 ─────


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_constant_total_timeout(value: ast.expr) -> bool:
    if not isinstance(value, ast.Call) or _call_name(value.func) != "ClientTimeout":
        return False
    if value.args:
        return False
    keywords = {kw.arg: kw.value for kw in value.keywords}
    total = keywords.get("total")
    return (
        set(keywords) == {"total"}
        and isinstance(total, ast.Name)
        and total.id == "TELEGRAM_REQUEST_TIMEOUT"
    )


def test_every_client_session_in_notification_has_constant_timeout():
    found: list[str] = []
    bad: list[str] = []
    for path in sorted(_NOTIFICATION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node.func) != "ClientSession":
                continue
            where = f"{path.name}:{node.lineno}"
            found.append(where)
            timeouts = [kw.value for kw in node.keywords if kw.arg == "timeout"]
            has_unpack = any(kw.arg is None for kw in node.keywords)
            if has_unpack or len(timeouts) != 1:
                bad.append(where)
            elif not _is_constant_total_timeout(timeouts[0]):
                bad.append(where)

    assert len(found) >= 4, found
    assert not bad, bad
