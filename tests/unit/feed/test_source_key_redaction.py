"""피드 소스의 로그·반환 사유·예외·CLI 출력에 API 키가 나타나지 않는다 (#3129).

모든 요청은 127.0.0.1의 테스트 서버로만 간다. 키는 가짜(`TEST…FAKE`)다.
불변식은 서버 동작 × 진입점 × 키의 곱으로 만든다(예외 종류를 열거하지 않는다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import web
from click.testing import CliRunner

from ante.feed.sources import base as base_mod
from ante.feed.sources import dart as dart_mod
from ante.feed.sources import data_go_kr as dg_mod
from ante.feed.sources.base import describe_source_error
from ante.feed.sources.dart import DARTSource
from ante.feed.sources.data_go_kr import DataGoKrSource

_KEY_SYMBOLS = "TEST+KEY/FAKE=="
_KEY_ALNUM = "TESTKEYFAKE0000"
_KEY_PREENCODED = "TEST%2BKEY%2FFAKE%3D%3D"
_KEYS = (_KEY_SYMBOLS, _KEY_ALNUM, _KEY_PREENCODED)
_SLOW_SECONDS = 1.0
_HOLD_SECONDS = 30.0
_HOLD_RECEIVED = threading.Event()
_HOLD_RELEASE = threading.Event()


def _key_forms(key: str) -> set[str]:
    """키의 원문과 URL 인코딩 꼴."""
    return {key, quote(key, safe=""), quote(key, safe="/"), quote(key, safe="/?:@")}


def _url_forms(key: str) -> set[str]:
    """주소에 실리는 꼴. 인코딩이 원문과 다르면 원문을 뺀다."""
    return (_key_forms(key) - {key}) or {key}


def _assert_no_key(text: str, where: str) -> None:
    assert "FAKE" not in text, f"{where}에 키 조각이 있다: {text!r}"
    for key in _KEYS:
        for form in _key_forms(key):
            assert form not in text, f"{where}에 키({form})가 있다: {text!r}"


# ── 127.0.0.1 테스트 서버 (별도 스레드) ─────────────────────────


_ECHO_CODES: dict[str, tuple[str, str]] = {
    "limit": ("020", "22"),
    "auth": ("010", "30"),
    "skip": ("100", "10"),
    "retry": ("800", "01"),
    "retryonce": ("900", "99"),
    "nodata": ("013", "013"),
}
_PLAIN_MSG = "SERVICE KEY IS NOT REGISTERED. check serviceKey crtfc_key (x)"
_RECEIVED_KEYS: list[str] = []


def _query_key(request: web.Request) -> str:
    return request.query.get("crtfc_key") or request.query.get("serviceKey") or ""


def _echo_payload(status: str, code: str, msg: str, total: Any = 0) -> Any:
    return {
        "status": status,
        "message": msg,
        "list": [],
        "response": {
            "header": {"resultCode": code, "resultMsg": msg},
            "body": {"totalCount": total, "items": {}},
        },
    }


def _echo_response(behavior: str, request: web.Request) -> web.StreamResponse | None:
    url = str(request.url)
    key = _query_key(request)
    kind, _, arg = behavior.partition("-")
    if kind == "echo":
        dart_code, dg_code = _ECHO_CODES.get(arg, (url, url))
        return web.json_response(_echo_payload(dart_code, dg_code, url))
    if kind == "plain":
        if arg == "total":
            return web.json_response(_echo_payload("000", "00", "NORMAL", "abc"))
        dart_code, dg_code = _ECHO_CODES[arg]
        return web.json_response(_echo_payload(dart_code, dg_code, _PLAIN_MSG))
    if kind == "ok":
        return web.json_response(_echo_payload("000", "00", "NORMAL"))
    if kind == "totalcount":
        payload = _echo_payload(url, "00", url, url)
        payload["response"]["body"]["items"] = {"item": url}
        return web.json_response(payload)
    if kind == "html":
        return web.Response(text=f"<html>{url} {key}</html>", content_type="text/html")
    if kind == "pad":
        cut = key.index("FAKE") + 5
        assert cut < len(key)
        return web.Response(
            text="x" * (200 - cut) + key + " " + url, content_type="text/html"
        )
    return None


async def _handle(request: web.Request) -> web.StreamResponse:
    behavior = request.match_info["behavior"]
    _RECEIVED_KEYS.append(_query_key(request))
    echoed = _echo_response(behavior, request)
    if echoed is not None:
        return echoed
    if behavior in ("500", "503"):
        return web.json_response(
            {"status": "800", "message": "server error"}, status=int(behavior)
        )
    if behavior == "500xml":
        return web.Response(
            status=500, body=b"<error/>", content_type="application/xml"
        )
    if behavior == "404":
        return web.json_response({"status": "800", "message": "nf"}, status=404)
    if behavior == "loop":
        raise web.HTTPFound(location=f"/loop/{request.match_info.get('rest', '')}")
    if behavior == "slow":
        await asyncio.sleep(_SLOW_SECONDS)
        return web.json_response({"status": "000"})
    if behavior == "hold":
        _HOLD_RECEIVED.set()
        await asyncio.to_thread(_HOLD_RELEASE.wait, _HOLD_SECONDS)
        return web.Response(text="held")
    return web.Response(status=503, text="Service Unavailable")


class _ServerThread:
    def __init__(self) -> None:
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._runner: web.AppRunner | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start())
        self._ready.set()
        self._loop.run_forever()

    async def _start(self) -> None:
        app = web.Application()
        app.router.add_route("GET", "/{behavior}/{rest:.*}", _handle)
        app.router.add_route("GET", "/{behavior}", _handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(10)

    def stop(self) -> None:
        assert self._runner is not None
        fut = asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._loop)
        fut.result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)

    def url(self, behavior: str) -> str:
        return f"http://127.0.0.1:{self.port}/{behavior}"


@pytest.fixture(scope="module")
def server() -> Iterator[_ServerThread]:
    srv = _ServerThread()
    srv.start()
    yield srv
    srv.stop()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for cls in (DARTSource, DataGoKrSource):
        monkeypatch.setattr(cls, "_backoff_delay", staticmethod(lambda *a, **k: 0.0))


@pytest.fixture
def raw_errors(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """도우미가 받은 예외의 종류와 원래 문자열(가리기 전)을 모은다."""
    seen: list[str] = []
    real = base_mod.describe_source_error

    def _spy(exc: BaseException, api_key: str) -> str:
        seen.append(f"{type(exc).__name__}: {exc}")
        return real(exc, api_key)

    monkeypatch.setattr(dart_mod, "describe_source_error", _spy, raising=False)
    monkeypatch.setattr(dg_mod, "describe_source_error", _spy, raising=False)
    return seen


# ── 도우미 단위 ─────────────────────────────────────────────


class TestDescribeSourceError:
    def test_removes_raw_and_encoded_key_keeps_diagnostics(self) -> None:
        msg = (
            "503, message='Service Unavailable', url='http://127.0.0.1:1/dg?"
            "serviceKey=TEST%2BKEY/FAKE%3D%3D&numOfRows=1&pageNo=1'"
        )
        exc = aiohttp.ClientError(msg)
        out = describe_source_error(exc, _KEY_SYMBOLS)
        _assert_no_key(out, "도우미 결과")
        assert out.startswith("ClientError: ")
        assert "503" in out
        assert "/dg?" in out
        assert "numOfRows=1" in out
        assert "pageNo=1" in out

    def test_empty_key_regex_only(self) -> None:
        msg = (
            "url='http://h/api/x.json?crtfc_key=TESTKEYFAKE0000&corp_code=1' "
            "and SERVICEKEY%3DTEST%2BKEY/FAKE%3D%3D&a=1 "
            "and 'http://h/dg?serviceKey=TEST+KEY/FAKE=='"
        )
        out = describe_source_error(RuntimeError(msg), "")
        _assert_no_key(out, "도우미 결과")
        assert "crtfc_key=***" in out
        assert "SERVICEKEY%3D***" in out
        assert "serviceKey=***'" in out
        assert "corp_code=1" in out
        assert "&a=1" in out

    def test_bare_key_without_url(self) -> None:
        out = describe_source_error(
            ValueError(f"bad token {_KEY_ALNUM} end"), _KEY_ALNUM
        )
        _assert_no_key(out, "도우미 결과")
        assert out == "ValueError: bad token *** end"

    def test_bare_encoded_key_without_url(self) -> None:
        out = describe_source_error(
            ValueError("got TEST%2BKEY%2FFAKE%3D%3D here"), _KEY_SYMBOLS
        )
        _assert_no_key(out, "도우미 결과")
        assert out == "ValueError: got *** here"

    def test_reencoded_key(self) -> None:
        out = describe_source_error(
            ValueError("x TEST%252BKEY%252FFAKE%253D%253D y"), _KEY_PREENCODED
        )
        _assert_no_key(out, "도우미 결과")

    def test_message_without_key_is_unchanged(self) -> None:
        msg = "Connection timeout to host http://h/api/x.json?corp_code=1&a=b"
        assert describe_source_error(TimeoutError(msg), _KEY_ALNUM) == (
            f"TimeoutError: {msg}"
        )

    def test_empty_key_does_not_touch_message(self) -> None:
        msg = "status=500 a=b"
        assert describe_source_error(OSError(msg), "") == f"OSError: {msg}"

    def test_empty_message_gives_type_name(self) -> None:
        assert describe_source_error(TimeoutError(), _KEY_ALNUM) == "TimeoutError"


# ── 불변식: 서버 동작 × 진입점 × 키 ──────────────────────────────

_BEHAVIORS = (
    "500",
    "503",
    "500xml",
    "404",
    "loop",
    "connect_timeout",
    "refused",
    "slow",
)
_ENTRIES = (
    "dart.fetch_financial",
    "dart.fetch_corp_codes",
    "dart.validate_credentials",
    "dg.fetch_by_date",
    "dg.validate_credentials",
)

_KEY_REACHES_SITE: dict[tuple[str, str], bool] = {
    ("500", "dart.fetch_financial"): True,
    ("503", "dart.fetch_financial"): True,
    ("500xml", "dart.fetch_financial"): True,
    ("500", "dg.fetch_by_date"): True,
    ("503", "dg.fetch_by_date"): True,
    ("500xml", "dg.fetch_by_date"): True,
    ("500xml", "dart.fetch_corp_codes"): True,
    ("500", "dart.validate_credentials"): True,
    ("503", "dart.validate_credentials"): True,
    ("500xml", "dart.validate_credentials"): True,
    ("404", "dart.validate_credentials"): True,
    ("500", "dg.validate_credentials"): True,
    ("503", "dg.validate_credentials"): True,
    ("500xml", "dg.validate_credentials"): True,
    ("404", "dg.validate_credentials"): True,
    **{(b, e): True for b in ("loop", "connect_timeout") for e in _ENTRIES},
}


async def _run_entry(
    entry: str, key: str, base_url: str, session: aiohttp.ClientSession | None
) -> Any:
    if entry.startswith("dart."):
        dart = DARTSource(
            api_key=key, session=session, max_retries=2, base_url=base_url
        )
        if entry == "dart.fetch_financial":
            return await dart.fetch_financial(["00126380"], "2024", "11011")
        if entry == "dart.fetch_corp_codes":
            return await dart.fetch_corp_codes()
        return await dart.validate_credentials()
    dg = DataGoKrSource(api_key=key, session=session, max_retries=2, base_url=base_url)
    if entry == "dg.fetch_by_date":
        return await dg.fetch_by_date("2026-11-27")
    return await dg.validate_credentials()


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("entry", _ENTRIES)
@pytest.mark.parametrize("behavior", _BEHAVIORS)
async def test_key_never_leaks(
    behavior: str,
    entry: str,
    key: str,
    server: _ServerThread,
    raw_errors: list[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    session: aiohttp.ClientSession | None = None
    hold: asyncio.Task[Any] | None = None
    if behavior == "refused":
        base_url = f"http://127.0.0.1:{_closed_port()}/x"
    elif behavior == "connect_timeout":
        base_url = server.url("x")
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=1),
            timeout=aiohttp.ClientTimeout(connect=0.2),
        )
        _HOLD_RECEIVED.clear()
        _HOLD_RELEASE.clear()
        hold = asyncio.ensure_future(session.get(server.url("hold")))
        assert await asyncio.to_thread(_HOLD_RECEIVED.wait, 10), "자리를 못 잡았다"
    else:
        if behavior == "slow":
            monkeypatch.setattr(dart_mod, "REQUEST_TIMEOUT", 0.2)
            monkeypatch.setattr(dg_mod, "REQUEST_TIMEOUT", 0.2)
        base_url = server.url(behavior)

    result: Any = None
    raised: BaseException | None = None
    try:
        result = await _run_entry(entry, key, base_url, session)
    except Exception as exc:
        raised = exc
    finally:
        if hold is not None:
            _HOLD_RELEASE.set()
            hold.cancel()
            await asyncio.gather(hold, return_exceptions=True)
        if session is not None:
            await session.close()

    feed_records = [r for r in caplog.records if r.name.startswith("ante.feed")]
    assert feed_records, "피드 로그가 한 건도 없다(빈 통과)"
    if entry.endswith("validate_credentials"):
        assert raised is None
        assert result[0] is None
        assert result[1]
        _assert_no_key(str(result), "반환값")
    else:
        assert raised is not None
        _assert_no_key(str(raised), "예외")
        assert any(r.levelno >= logging.WARNING for r in feed_records)

    _assert_no_key(caplog.text, "로그")

    expected_kind = {"connect_timeout": "ConnectionTimeoutError: ", "slow": "Timeout"}
    if behavior in expected_kind:
        assert raw_errors
        assert all(r.startswith(expected_kind[behavior]) for r in raw_errors), (
            f"원래 예외가 {behavior}가 아니다: {raw_errors!r}"
        )

    if _KEY_REACHES_SITE.get((behavior, entry), False):
        assert any(any(f in raw for f in _url_forms(key)) for raw in raw_errors), (
            f"가리기 전 예외 문자열에 인코딩된 키가 없다: {raw_errors!r}"
        )


def test_matrix_size() -> None:
    assert len(_BEHAVIORS) * len(_ENTRIES) * len(_KEYS) == 120
    assert len(_KEY_REACHES_SITE) == 25


# ── CLI ─────────────────────────────────────────────────────


class _CurrentStderr(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        sys.stderr.write(self.format(record) + "\n")
        sys.stderr.flush()


@pytest.fixture
def cli_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: _ServerThread
) -> Iterator[tuple[CliRunner, Path]]:
    from ante.feed.config import FeedConfig
    from ante.member.models import Member, MemberRole, MemberType

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("ANTE_DART_API_KEY", raising=False)
    monkeypatch.delenv("ANTE_DATAGOKR_API_KEY", raising=False)
    monkeypatch.setitem(
        DARTSource.__init__.__kwdefaults__, "base_url", server.url("all503")
    )
    monkeypatch.setitem(
        DataGoKrSource.__init__.__kwdefaults__, "base_url", server.url("all503")
    )

    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "config.toml").write_text(
        "[schedule]\n"
        'daily_at = "16:00"\n'
        'backfill_at = "01:00"\n'
        'backfill_since = "2024-01-01"\n'
        "\n"
        "[guard]\n"
        "blocked_days = []\n"
        "blocked_hours = []\n"
        "pause_during_trading = false\n"
    )
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()
    cfg = FeedConfig(str(data_dir))
    cfg.set_api_key("ANTE_DART_API_KEY", _KEY_ALNUM)
    cfg.set_api_key("ANTE_DATAGOKR_API_KEY", _KEY_SYMBOLS)

    master = Member(
        member_id="test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Test Master",
        status="active",
        scopes=[],
    )

    def _set_member(ctx: object) -> None:
        import click

        click.get_current_context().obj = click.get_current_context().obj or {}
        click.get_current_context().obj["member"] = master

    handler = _CurrentStderr()
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)
    with patch("ante.cli.main.authenticate_member", side_effect=_set_member):
        yield CliRunner(mix_stderr=False), data_dir
    logging.getLogger().removeHandler(handler)


def _assert_files_have_no_key(data_dir: Path) -> None:
    for path in data_dir.rglob("*"):
        if path.is_file() and path.name != ".env":
            _assert_no_key(path.read_bytes().decode("utf-8", "replace"), str(path))


def test_cli_config_check_json_has_no_key(
    cli_env: tuple[CliRunner, Path], caplog: pytest.LogCaptureFixture
) -> None:
    from ante.cli.main import cli

    caplog.set_level(logging.DEBUG)
    runner, data_dir = cli_env
    result = runner.invoke(
        cli,
        ["--format", "json", "feed", "config", "check", "--data-path", str(data_dir)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    keys = {k["key"]: k for k in payload["keys"]}
    for name in ("ANTE_DART_API_KEY", "ANTE_DATAGOKR_API_KEY"):
        assert keys[name]["valid"] is None
        assert "503" in keys[name]["detail"]
    _assert_no_key(result.stdout, "stdout")
    _assert_no_key(result.stderr, "stderr")
    _assert_no_key(caplog.text, "로그")


def test_cli_config_check_text_has_no_key(
    cli_env: tuple[CliRunner, Path], caplog: pytest.LogCaptureFixture
) -> None:
    from ante.cli.main import cli

    caplog.set_level(logging.DEBUG)
    runner, data_dir = cli_env
    result = runner.invoke(
        cli, ["feed", "config", "check", "--data-path", str(data_dir)]
    )
    assert result.exit_code == 0, result.output
    assert "검증 불가" in result.stdout
    _assert_no_key(result.stdout, "stdout")
    _assert_no_key(result.stderr, "stderr")
    _assert_no_key(caplog.text, "로그")


@pytest.mark.parametrize("fmt_args", [[], ["--format", "json"]])
def test_cli_run_daily_has_no_key(
    fmt_args: list[str],
    cli_env: tuple[CliRunner, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ante.cli.main import cli

    caplog.set_level(logging.DEBUG)
    runner, data_dir = cli_env
    result = runner.invoke(
        cli,
        [*fmt_args, "feed", "run", "daily", "--data-path", str(data_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "재시도" in result.stderr
    _assert_no_key(result.stdout, "stdout")
    _assert_no_key(result.stderr, "stderr")
    _assert_no_key(caplog.text, "로그")
    _assert_files_have_no_key(data_dir)


# ── 서버가 응답에 요청 주소를 되돌려 주는 경우 (#3141) ─────────────────

_ECHO_BEHAVIORS = (
    "echo-limit",
    "echo-auth",
    "echo-skip",
    "echo-retry",
    "echo-retryonce",
    "echo-nodata",
    "echo-unknown",
    "html",
    "pad",
    "totalcount",
)
_NON_JSON = ("html", "pad")
_JSON_DECODING_ENTRIES = ("dart.fetch_financial", "dg.fetch_by_date")


def _nothing_to_hide(behavior: str, entry: str) -> bool:
    """서버 값이 어떤 문구에도 실리지 않는 칸."""
    if entry.endswith("validate_credentials"):
        return behavior != "echo-auth"
    if behavior in _NON_JSON:
        return entry in _JSON_DECODING_ENTRIES
    return (behavior, entry) == ("echo-nodata", "dart.fetch_financial")


_ECHO_CELLS = [
    (b, e)
    for b in _ECHO_BEHAVIORS
    for e in _ENTRIES
    if not (b in _NON_JSON and e.endswith("validate_credentials"))
]


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize(("behavior", "entry"), _ECHO_CELLS)
async def test_server_echo_never_leaks_key(
    behavior: str,
    entry: str,
    key: str,
    server: _ServerThread,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _RECEIVED_KEYS.clear()
    result: Any = None
    raised: BaseException | None = None
    try:
        result = await _run_entry(entry, key, server.url(behavior), None)
    except Exception as exc:
        raised = exc

    assert key in _RECEIVED_KEYS, (
        f"서버가 키를 받지 못했다(빈 통과): {_RECEIVED_KEYS!r}"
    )
    _assert_no_key(caplog.text, "로그")
    _assert_no_key(str(result), "반환값")
    _assert_no_key(str(raised), "예외")
    if _nothing_to_hide(behavior, entry):
        return
    shown = f"{caplog.text}\n{result}\n{raised}"
    assert "***" in shown, f"가린 흔적이 없다(빈 통과): {shown!r}"


def test_echo_matrix_size() -> None:
    assert len(_ECHO_CELLS) == 46
    assert len(_ECHO_CELLS) * len(_KEYS) == 138
    assert sum(_nothing_to_hide(b, e) for b, e in _ECHO_CELLS) == 19


async def test_total_count_error_keeps_type_and_prefix(server: _ServerThread) -> None:
    dg = DataGoKrSource(
        api_key=_KEY_SYMBOLS, max_retries=2, base_url=server.url("totalcount")
    )
    with pytest.raises(ValueError) as info:
        await dg.fetch_by_date("2026-11-27")
    assert type(info.value) is ValueError
    text = str(info.value)
    assert text.startswith("invalid literal for int() with base 10: 'http://")
    assert "serviceKey=***" in text
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    _assert_no_key(text, "예외")


_PLAIN_EXPECTED = (
    ("plain-limit", "dart.fetch_financial", f"DART 일일 한도 초과: {_PLAIN_MSG}"),
    ("plain-limit", "dart.fetch_corp_codes", f"DART 일일 한도 초과: {_PLAIN_MSG}"),
    (
        "plain-auth",
        "dart.validate_credentials",
        f"(False, '인증 실패 (status=010): {_PLAIN_MSG}')",
    ),
    ("plain-limit", "dg.fetch_by_date", f"일일 한도 초과: {_PLAIN_MSG}"),
    (
        "plain-auth",
        "dg.validate_credentials",
        f"(False, '인증 실패 (code=30): {_PLAIN_MSG}')",
    ),
    (
        "plain-total",
        "dg.fetch_by_date",
        "invalid literal for int() with base 10: 'abc'",
    ),
)


@pytest.mark.parametrize(("behavior", "entry", "expected"), _PLAIN_EXPECTED)
async def test_message_without_key_is_unchanged_at_sites(
    behavior: str, entry: str, expected: str, server: _ServerThread
) -> None:
    try:
        shown = str(await _run_entry(entry, _KEY_ALNUM, server.url(behavior), None))
    except Exception as exc:
        shown = str(exc)
    assert shown == expected


@pytest.mark.parametrize(
    ("behavior", "entry", "expected"),
    [
        ("ok", "dart.fetch_financial", "[]"),
        ("ok", "dg.fetch_by_date", "[]"),
        ("echo-auth", "dart.validate_credentials", "False"),
        ("echo-auth", "dg.validate_credentials", "False"),
    ],
)
async def test_short_key_classifies_on_original_code(
    behavior: str, entry: str, expected: str, server: _ServerThread
) -> None:
    result = await _run_entry(entry, "0", server.url(behavior), None)
    shown = str(result[0]) if isinstance(result, tuple) else str(result)
    assert shown == expected


def _use_behavior(
    monkeypatch: pytest.MonkeyPatch, server: _ServerThread, behavior: str
) -> None:
    for cls in (DARTSource, DataGoKrSource):
        monkeypatch.setitem(
            cls.__init__.__kwdefaults__, "base_url", server.url(behavior)
        )


@pytest.mark.parametrize("behavior", ["echo-limit", "totalcount"])
@pytest.mark.parametrize("fmt_args", [[], ["--format", "json"]])
def test_cli_run_daily_echo_has_no_key(
    behavior: str,
    fmt_args: list[str],
    cli_env: tuple[CliRunner, Path],
    server: _ServerThread,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ante.cli.main import cli

    caplog.set_level(logging.DEBUG)
    runner, data_dir = cli_env
    _use_behavior(monkeypatch, server, behavior)
    _RECEIVED_KEYS.clear()
    result = runner.invoke(
        cli,
        [*fmt_args, "feed", "run", "daily", "--data-path", str(data_dir)],
    )
    assert result.exit_code == 0, result.output
    assert _KEY_SYMBOLS in _RECEIVED_KEYS
    assert _KEY_ALNUM in _RECEIVED_KEYS
    _assert_no_key(result.stdout, "stdout")
    _assert_no_key(result.stderr, "stderr")
    _assert_no_key(caplog.text, "로그")
    _assert_files_have_no_key(data_dir)
    reports = [p for p in (data_dir / ".feed" / "reports").rglob("*") if p.is_file()]
    assert reports, "리포트 파일이 없다(빈 통과)"
    saved = "".join(p.read_text(encoding="utf-8") for p in reports)
    assert "***" in saved
    if behavior == "totalcount":
        assert "invalid literal for int() with base 10:" in saved


@pytest.mark.parametrize("fmt_args", [[], ["--format", "json"]])
def test_cli_config_check_echo_auth_has_no_key(
    fmt_args: list[str],
    cli_env: tuple[CliRunner, Path],
    server: _ServerThread,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ante.cli.main import cli

    caplog.set_level(logging.DEBUG)
    runner, data_dir = cli_env
    _use_behavior(monkeypatch, server, "echo-auth")
    result = runner.invoke(
        cli,
        [*fmt_args, "feed", "config", "check", "--data-path", str(data_dir)],
    )
    assert "인증 실패" in result.stdout
    if fmt_args:
        keys = {k["key"]: k for k in json.loads(result.stdout)["keys"]}
        for name in ("ANTE_DART_API_KEY", "ANTE_DATAGOKR_API_KEY"):
            assert keys[name]["valid"] is False
            assert "***" in keys[name]["detail"]
    _assert_no_key(result.stdout, "stdout")
    _assert_no_key(result.stderr, "stderr")
    _assert_no_key(caplog.text, "로그")
