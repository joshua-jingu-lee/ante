"""``ante bot list/info/positions/signal-key`` (read) runtime IPC 라우팅 lock (#2112).

## 배경

``bot list/info/positions/signal-key`` 는 스펙(``docs/specs/cli/03-commands.md`` /
``cli_registry`` / ``docs/specs/ipc/ipc.md``)상 ``runtime IPC + snapshot
fallback`` 으로 정의되어 있으나, CLI 가 IPC 를 시도하지 않고 직접 DB snapshot
만 조회했다. #2112 는 4종을 IPC 우선 + 서버 정지(``IPC_SERVER_NOT_RUNNING``)
시 기존 snapshot DB fallback 으로 라우팅한다.

## 회귀 lock (이슈 본문 검증 (a)~(f))

- (a) 서버 실행 → 각 명령 ``ipc_send`` 호출 + 직접 DB 경로
  (``_create_services`` / ``SignalKeyManager`` / ``open_cli_db`` /
  ``TradeService``) **미호출**.
- (b) 서버 정지(``IPC_SERVER_NOT_RUNNING``) → fallback DB 경로 수행 + exit 0
  (**#2111 rotate 와 정반대로 fallback 수행 lock**).
- (c) shape parity: IPC result ↔ fallback result 공통 핵심키 동일.
- (d) 미존재 봇 → ``BOT_NOT_FOUND`` 양쪽 exit 1; signal-key 미발급 → 양쪽
  동일 처리.
- (e) ``IPC_TIMEOUT`` / server-error → fallback 없이 surface exit 1.
- (f) positions: ``trade_service`` None(미구성) vs 빈 포지션(0개) 구분;
  account scoping(타계좌 누출 차단) 양쪽 동일.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="read-ipc-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Read IPC Master",
    status="active",
    scopes=[],
)


def _server_not_running_exc() -> click.ClickException:
    """``ServerNotRunningError`` → ``ipc_send`` ClickException 대역."""
    exc = click.ClickException(
        "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
    )
    exc.ipc_error_code = "IPC_SERVER_NOT_RUNNING"  # type: ignore[attr-defined]
    exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
    return exc


def _timeout_exc() -> click.ClickException:
    exc = click.ClickException("서버 응답 시간 초과")
    exc.ipc_error_code = "IPC_TIMEOUT"  # type: ignore[attr-defined]
    exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
    return exc


def _server_error_exc(code: str, message: str) -> click.ClickException:
    """서버 error envelope → ``ipc_send`` ClickException 대역."""
    exc = click.ClickException(f"{code}: {message}")
    exc.ipc_error_code = code  # type: ignore[attr-defined]
    exc.ipc_error_message = message  # type: ignore[attr-defined]
    return exc


def _parse_json(stdout: str) -> dict:
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.splitlines()[-1])


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _invoke(args: list[str], *, patches: list):
    """auth 우회 + 주어진 patch context 하에 CLI 호출."""
    runner = _runner()

    def _auth_set(ctx):  # noqa: ANN001, ANN202
        ctx.obj = ctx.obj or {}
        ctx.obj["member"] = _MASTER

    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_auth_set)
        )
        stack.enter_context(
            patch("ante.cli.main.get_db_path", return_value="/tmp/unused-read-ipc.db")
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args)


# 직접 DB cold-path 진입을 막는 가드 (서버 실행 중 IPC-only 검증용).
def _guard_direct_db() -> list:
    return [
        patch(
            "ante.cli.commands.bot._create_services",
            side_effect=AssertionError(
                "서버 실행 중인데 _create_services cold-path 가 호출됨 (#2112 위반)"
            ),
        ),
        patch(
            "ante.cli.commands.bot.open_cli_db",
            side_effect=AssertionError(
                "서버 실행 중인데 open_cli_db cold-path 가 호출됨 (#2112 위반)"
            ),
        ),
        patch(
            "ante.bot.signal_key.SignalKeyManager",
            side_effect=AssertionError(
                "서버 실행 중인데 SignalKeyManager cold-path 가 호출됨 (#2112 위반)"
            ),
        ),
        patch(
            "ante.trade.service.TradeService",
            side_effect=AssertionError(
                "서버 실행 중인데 TradeService cold-path 가 호출됨 (#2112 위반)"
            ),
        ),
    ]


# ── (a) 서버 실행 중 → IPC 라우팅 + 직접 DB 미호출 ────────────────────────────


class TestServerRunningRoutesToIpc:
    def test_list_routes_to_ipc(self) -> None:
        mock_send = AsyncMock(
            return_value={
                "bots": [
                    {
                        "bot_id": "bot-1",
                        "name": "B1",
                        "strategy_id": "s1",
                        "account_id": "acc-a",
                        "status": "stopped",
                        "created_at": None,
                    }
                ]
            }
        )
        result = _invoke(
            ["--format", "json", "bot", "list"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert mock_send.await_args.args[0] == "bot.list"
        payload = _parse_json(result.stdout)
        assert [b["bot_id"] for b in payload["bots"]] == ["bot-1"]

    def test_list_account_filter_passed_to_ipc(self) -> None:
        mock_send = AsyncMock(return_value={"bots": []})
        result = _invoke(
            ["--format", "json", "bot", "list", "--account", "acc-a"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert mock_send.await_args.args[0] == "bot.list"
        assert mock_send.await_args.args[1] == {"account_id": "acc-a"}

    def test_info_routes_to_ipc(self) -> None:
        mock_send = AsyncMock(
            return_value={
                "bot": {
                    "bot_id": "bot-1",
                    "name": "B1",
                    "status": "running",
                    "account_id": "acc-a",
                    "strategy_id": "s1",
                }
            }
        )
        result = _invoke(
            ["--format", "json", "bot", "info", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert mock_send.await_args.args[0] == "bot.info"
        assert mock_send.await_args.args[1] == {"bot_id": "bot-1"}
        payload = _parse_json(result.stdout)
        assert payload["bot_id"] == "bot-1"
        assert payload["status"] == "running"

    def test_positions_routes_to_ipc(self) -> None:
        mock_send = AsyncMock(
            return_value={
                "positions": [
                    {
                        "symbol": "AAA",
                        "quantity": 1.0,
                        "avg_entry_price": 100.0,
                        "realized_pnl": 10.0,
                    }
                ]
            }
        )
        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert mock_send.await_args.args[0] == "bot.positions"
        assert mock_send.await_args.args[1] == {"bot_id": "bot-1"}
        payload = _parse_json(result.stdout)
        assert [p["symbol"] for p in payload["positions"]] == ["AAA"]

    def test_signal_key_read_routes_to_ipc(self) -> None:
        mock_send = AsyncMock(return_value={"bot_id": "bot-1", "signal_key": "sk_live"})
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert mock_send.await_args.args[0] == "bot.signal_key"
        assert mock_send.await_args.args[1] == {"bot_id": "bot-1"}
        payload = _parse_json(result.stdout)
        assert payload["signal_key"] == "sk_live"

    def test_signal_key_read_does_not_use_rotate_command(self) -> None:
        """read 경로(rotate 미지정)는 ``bot.signal_key`` (read) 만 호출하고
        ``bot.signal_key.rotate`` (#2111 mutating) 는 호출하지 않는다."""
        mock_send = AsyncMock(return_value={"bot_id": "bot-1", "signal_key": "sk_live"})
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        called_commands = [c.args[0] for c in mock_send.await_args_list]
        assert "bot.signal_key.rotate" not in called_commands
        assert called_commands == ["bot.signal_key"]


# ── (b) 서버 정지(IPC_SERVER_NOT_RUNNING) → fallback DB 경로 수행 + exit 0 ────


def _make_db(*, fetch_one=None, fetch_all=None) -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    if fetch_one is not None:
        db.fetch_one = AsyncMock(side_effect=fetch_one)
    if fetch_all is not None:
        db.fetch_all = AsyncMock(side_effect=fetch_all)
    return db


def _create_services_cm(db: MagicMock):
    """``_create_services`` async context manager 대역."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm(ctx=None):  # noqa: ANN001, ANN202
        yield db, MagicMock(), MagicMock(), MagicMock()

    return _cm


def _open_cli_db_cm(db: MagicMock):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm(ctx):  # noqa: ANN001, ANN202
        yield db

    return _cm


class TestServerStoppedFallsBackToSnapshot:
    """서버 정지 시 직접 DB snapshot fallback 을 수행한다 (#2111 rotate 와 정반대)."""

    def test_list_falls_back_to_db(self) -> None:
        mock_send = AsyncMock(side_effect=_server_not_running_exc())
        rows = [
            {
                "bot_id": "bot-db",
                "name": "DBBot",
                "strategy_id": "s1",
                "account_id": "acc-a",
                "status": "stopped",
                "created_at": "2026-01-01T00:00:00",
            }
        ]
        db = _make_db(fetch_all=lambda *a, **k: rows)
        result = _invoke(
            ["--format", "json", "bot", "list"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = _parse_json(result.stdout)
        assert [b["bot_id"] for b in payload["bots"]] == ["bot-db"]
        db.fetch_all.assert_awaited()

    def test_info_falls_back_to_db(self) -> None:
        mock_send = AsyncMock(side_effect=_server_not_running_exc())
        row = {
            "bot_id": "bot-db",
            "name": "DBBot",
            "strategy_id": "s1",
            "account_id": "acc-a",
            "status": "stopped",
            "created_at": "2026-01-01T00:00:00",
        }
        db = _make_db(fetch_one=lambda *a, **k: row)
        result = _invoke(
            ["--format", "json", "bot", "info", "bot-db"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = _parse_json(result.stdout)
        assert payload["bot_id"] == "bot-db"
        db.fetch_one.assert_awaited()

    def test_signal_key_read_falls_back_to_db(self) -> None:
        mock_send = AsyncMock(side_effect=_server_not_running_exc())
        db = _make_db(fetch_one=lambda *a, **k: {"strategy_id": "s1"})
        skm = MagicMock()
        skm.initialize = AsyncMock()
        skm.get_key = AsyncMock(return_value="sk_db")
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-db"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
                patch("ante.bot.signal_key.SignalKeyManager", return_value=skm),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = _parse_json(result.stdout)
        assert payload["signal_key"] == "sk_db"
        skm.get_key.assert_awaited()

    def test_positions_falls_back_to_db(self) -> None:
        mock_send = AsyncMock(side_effect=_server_not_running_exc())
        db = _make_db(fetch_one=lambda *a, **k: {"account_id": "acc-a"})
        position = SimpleNamespace(
            symbol="AAA", quantity=1.0, avg_entry_price=100.0, realized_pnl=10.0
        )
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[position])
        pos_history = MagicMock()
        pos_history.initialize = AsyncMock()
        recorder = MagicMock()
        recorder.initialize = AsyncMock()
        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-db"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                patch("ante.cli.commands.bot.open_cli_db", new=_open_cli_db_cm(db)),
                patch("ante.trade.position.PositionHistory", return_value=pos_history),
                patch("ante.trade.recorder.TradeRecorder", return_value=recorder),
                patch(
                    "ante.trade.performance.PerformanceTracker",
                    return_value=MagicMock(),
                ),
                patch("ante.trade.service.TradeService", return_value=trade_service),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = _parse_json(result.stdout)
        assert [p["symbol"] for p in payload["positions"]] == ["AAA"]
        # account scoping 보존: 봇 계좌(acc-a) 로 스코핑.
        trade_service.get_positions.assert_awaited_once_with(
            "bot-db", account_id="acc-a"
        )


# ── (c) shape parity: IPC result ↔ fallback result 공통 핵심키 ────────────────


class TestShapeParity:
    def test_list_parity(self) -> None:
        bots_payload = [
            {
                "bot_id": "bot-1",
                "name": "B1",
                "strategy_id": "s1",
                "account_id": "acc-a",
                "status": "stopped",
                "created_at": None,
            }
        ]
        ipc_send = AsyncMock(return_value={"bots": bots_payload})
        ipc_res = _invoke(
            ["--format", "json", "bot", "list"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
                *_guard_direct_db(),
            ],
        )
        db_rows = [dict(b, created_at="2026-01-01") for b in bots_payload]
        db = _make_db(fetch_all=lambda *a, **k: db_rows)
        fb_res = _invoke(
            ["--format", "json", "bot", "list"],
            patches=[
                patch(
                    "ante.cli.commands.ipc_helpers.ipc_send",
                    new=AsyncMock(side_effect=_server_not_running_exc()),
                ),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
            ],
        )
        ipc_keys = set(_parse_json(ipc_res.stdout))
        fb_keys = set(_parse_json(fb_res.stdout))
        assert "bots" in ipc_keys and "bots" in fb_keys
        ipc_bot = _parse_json(ipc_res.stdout)["bots"][0]
        fb_bot = _parse_json(fb_res.stdout)["bots"][0]
        common = {"bot_id", "name", "strategy_id", "account_id", "status"}
        assert {k: ipc_bot[k] for k in common} == {k: fb_bot[k] for k in common}

    def test_signal_key_parity(self) -> None:
        ipc_send = AsyncMock(return_value={"bot_id": "bot-1", "signal_key": "sk"})
        ipc_res = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
                *_guard_direct_db(),
            ],
        )
        db = _make_db(fetch_one=lambda *a, **k: {"strategy_id": "s1"})
        skm = MagicMock()
        skm.initialize = AsyncMock()
        skm.get_key = AsyncMock(return_value="sk")
        fb_res = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch(
                    "ante.cli.commands.ipc_helpers.ipc_send",
                    new=AsyncMock(side_effect=_server_not_running_exc()),
                ),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
                patch("ante.bot.signal_key.SignalKeyManager", return_value=skm),
            ],
        )
        ipc = _parse_json(ipc_res.stdout)
        fb = _parse_json(fb_res.stdout)
        assert {"bot_id", "signal_key"} <= set(ipc)
        assert {k: ipc[k] for k in ("bot_id", "signal_key")} == {
            k: fb[k] for k in ("bot_id", "signal_key")
        }


# ── (d) 미존재 봇 → BOT_NOT_FOUND 양쪽 exit 1; signal-key 미발급 동일 처리 ────


class TestMissingResource:
    def test_info_ipc_bot_not_found(self) -> None:
        mock_send = AsyncMock(
            side_effect=_server_error_exc("BOT_NOT_FOUND", "봇을 찾을 수 없습니다")
        )
        result = _invoke(
            ["--format", "json", "bot", "info", "missing"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "BOT_NOT_FOUND"

    def test_info_fallback_bot_not_found(self) -> None:
        db = _make_db(fetch_one=lambda *a, **k: None)
        result = _invoke(
            ["--format", "json", "bot", "info", "missing"],
            patches=[
                patch(
                    "ante.cli.commands.ipc_helpers.ipc_send",
                    new=AsyncMock(side_effect=_server_not_running_exc()),
                ),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "BOT_NOT_FOUND"

    def test_positions_ipc_bot_not_found(self) -> None:
        mock_send = AsyncMock(
            side_effect=_server_error_exc("BOT_NOT_FOUND", "봇을 찾을 수 없습니다")
        )
        result = _invoke(
            ["--format", "json", "bot", "positions", "missing"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "BOT_NOT_FOUND"

    def test_signal_key_ipc_bot_not_found(self) -> None:
        mock_send = AsyncMock(
            side_effect=_server_error_exc("BOT_NOT_FOUND", "봇을 찾을 수 없습니다")
        )
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "missing"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "BOT_NOT_FOUND"

    def test_signal_key_ipc_not_set(self) -> None:
        """IPC signal_key None → ``SIGNAL_KEY_NOT_SET`` (fallback 과 동일)."""
        mock_send = AsyncMock(return_value={"bot_id": "bot-1", "signal_key": None})
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "SIGNAL_KEY_NOT_SET"

    def test_signal_key_fallback_not_set(self) -> None:
        db = _make_db(fetch_one=lambda *a, **k: {"strategy_id": "s1"})
        skm = MagicMock()
        skm.initialize = AsyncMock()
        skm.get_key = AsyncMock(return_value=None)
        result = _invoke(
            ["--format", "json", "bot", "signal-key", "bot-1"],
            patches=[
                patch(
                    "ante.cli.commands.ipc_helpers.ipc_send",
                    new=AsyncMock(side_effect=_server_not_running_exc()),
                ),
                patch(
                    "ante.cli.commands.bot._create_services",
                    new=_create_services_cm(db),
                ),
                patch("ante.bot.signal_key.SignalKeyManager", return_value=skm),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "SIGNAL_KEY_NOT_SET"


# ── (e) IPC_TIMEOUT / server-error → fallback 없이 surface exit 1 ─────────────


class TestNonFallbackErrorsSurface:
    @pytest.mark.parametrize(
        "command,args",
        [
            ("bot.list", ["bot", "list"]),
            ("bot.info", ["bot", "info", "bot-1"]),
            ("bot.positions", ["bot", "positions", "bot-1"]),
            ("bot.signal_key", ["bot", "signal-key", "bot-1"]),
        ],
    )
    def test_timeout_surfaces_no_fallback(self, command: str, args: list[str]) -> None:
        mock_send = AsyncMock(side_effect=_timeout_exc())
        result = _invoke(
            ["--format", "json", *args],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "IPC_TIMEOUT"

    @pytest.mark.parametrize(
        "args",
        [
            ["bot", "list"],
            ["bot", "info", "bot-1"],
            ["bot", "positions", "bot-1"],
            ["bot", "signal-key", "bot-1"],
        ],
    )
    def test_server_error_surfaces_no_fallback(self, args: list[str]) -> None:
        mock_send = AsyncMock(
            side_effect=_server_error_exc("EXECUTION_ERROR", "서버 내부 오류")
        )
        result = _invoke(
            ["--format", "json", *args],
            patches=[
                patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
                *_guard_direct_db(),
            ],
        )
        assert result.exit_code == 1, result.stdout + result.stderr
        assert _parse_json(result.stdout)["code"] == "EXECUTION_ERROR"


# ── (f) positions: trade_service None(미구성) vs 빈 포지션(0개) 구분 ──────────


class TestPositionsServiceMissingVsEmpty:
    """IPC handler 가 ``trade_service`` 부재(미구성)와 빈 포지션(0개)을 모두
    graceful 처리하되 의미가 다름을 명시 검증한다 (#2112 Codex condition 2).

    두 경우 모두 CLI 출력은 ``positions=[]`` + exit 0 (빈 collection) 이지만,
    handler 레벨에서 trade_service None 경로(서비스 미구성)와 empty positions
    경로(0개 포지션)가 분리되어 동작함을 직접 검증한다.
    """

    @pytest.mark.asyncio
    async def test_handler_trade_service_none_returns_empty(self) -> None:
        from ante.ipc.registry import _handle_bot_positions

        bot = SimpleNamespace(config=SimpleNamespace(account_id="acc-a"))
        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(get_bot=lambda _id: bot),
            # trade_service 속성 자체가 없는 legacy registry 모사.
        )
        result = await _handle_bot_positions(svc, {"bot_id": "bot-1"}, "cli")
        # 미구성 → 빈 collection graceful (조회 불가 아님; 봇은 존재).
        assert result == {"positions": []}

    @pytest.mark.asyncio
    async def test_handler_empty_positions_distinct_from_missing_service(self) -> None:
        from ante.ipc.registry import _handle_bot_positions

        bot = SimpleNamespace(config=SimpleNamespace(account_id="acc-a"))
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])  # 0 포지션
        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(get_bot=lambda _id: bot),
            trade_service=trade_service,
        )
        result = await _handle_bot_positions(svc, {"bot_id": "bot-1"}, "cli")
        assert result == {"positions": []}
        # 빈 포지션 경로는 get_positions 를 봇 계좌로 스코핑 호출했다 — 미구성
        # 경로(get_positions 미호출)와 구분된다.
        trade_service.get_positions.assert_awaited_once_with(
            "bot-1", account_id="acc-a"
        )

    @pytest.mark.asyncio
    async def test_handler_missing_bot_raises(self) -> None:
        from ante.bot.exceptions import BotNotFoundError
        from ante.ipc.registry import _handle_bot_positions

        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(get_bot=lambda _id: None),
            trade_service=MagicMock(),
        )
        with pytest.raises(BotNotFoundError):
            await _handle_bot_positions(svc, {"bot_id": "missing"}, "cli")

    @pytest.mark.asyncio
    async def test_handler_account_scoping_lock(self) -> None:
        """포지션 조회가 항상 봇 계좌(account_id)로 스코핑됨 (타계좌 누출 차단)."""
        from ante.ipc.registry import _handle_bot_positions

        bot = SimpleNamespace(config=SimpleNamespace(account_id="acc-scoped"))
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])
        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(get_bot=lambda _id: bot),
            trade_service=trade_service,
        )
        await _handle_bot_positions(svc, {"bot_id": "bot-1"}, "cli")
        trade_service.get_positions.assert_awaited_once_with(
            "bot-1", account_id="acc-scoped"
        )


# ── handler-level list/info/signal_key 직접 검증 ──────────────────────────────


class TestReadHandlersUnit:
    @pytest.mark.asyncio
    async def test_list_projects_six_keys_and_defaults_created_at(self) -> None:
        """live get_info 에 created_at 부재 → None 기본값 보장 (Codex condition 1)."""
        from ante.ipc.registry import _handle_bot_list

        live_info = {
            "bot_id": "bot-1",
            "name": "B1",
            "strategy_id": "s1",
            "account_id": "acc-a",
            "status": "running",
            "interval_seconds": 60,  # projection 에서 제외되는 추가 키
        }
        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(list_bots=lambda: [live_info])
        )
        result = await _handle_bot_list(svc, {}, "cli")
        assert list(result.keys()) == ["bots"]
        bot = result["bots"][0]
        assert set(bot.keys()) == {
            "bot_id",
            "name",
            "strategy_id",
            "account_id",
            "status",
            "created_at",
        }
        assert bot["created_at"] is None  # live 부재 → None 기본값
        assert "interval_seconds" not in bot  # 6-key projection 만

    @pytest.mark.asyncio
    async def test_list_account_filter(self) -> None:
        from ante.ipc.registry import _handle_bot_list

        bots = [
            {
                "bot_id": "b1",
                "account_id": "acc-a",
                "name": "",
                "strategy_id": "",
                "status": "",
            },
            {
                "bot_id": "b2",
                "account_id": "acc-b",
                "name": "",
                "strategy_id": "",
                "status": "",
            },
        ]
        svc = SimpleNamespace(bot_manager=SimpleNamespace(list_bots=lambda: bots))
        result = await _handle_bot_list(svc, {"account_id": "acc-b"}, "cli")
        assert [b["bot_id"] for b in result["bots"]] == ["b2"]

    @pytest.mark.asyncio
    async def test_info_missing_raises(self) -> None:
        from ante.bot.exceptions import BotNotFoundError
        from ante.ipc.registry import _handle_bot_info

        svc = SimpleNamespace(bot_manager=SimpleNamespace(get_bot=lambda _id: None))
        with pytest.raises(BotNotFoundError):
            await _handle_bot_info(svc, {"bot_id": "missing"}, "cli")

    @pytest.mark.asyncio
    async def test_signal_key_read_missing_raises(self) -> None:
        from ante.bot.exceptions import BotNotFoundError
        from ante.ipc.registry import _handle_bot_signal_key

        svc = SimpleNamespace(bot_manager=SimpleNamespace(get_bot=lambda _id: None))
        with pytest.raises(BotNotFoundError):
            await _handle_bot_signal_key(svc, {"bot_id": "missing"}, "cli")

    @pytest.mark.asyncio
    async def test_signal_key_read_none_allowed(self) -> None:
        from ante.ipc.registry import _handle_bot_signal_key

        bot = SimpleNamespace(config=SimpleNamespace(account_id="acc-a"))
        svc = SimpleNamespace(
            bot_manager=SimpleNamespace(
                get_bot=lambda _id: bot,
                get_signal_key=AsyncMock(return_value=None),
            )
        )
        result = await _handle_bot_signal_key(svc, {"bot_id": "bot-1"}, "cli")
        assert result == {"bot_id": "bot-1", "signal_key": None}
