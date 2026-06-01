"""#2137: ``ante bot positions <bot_id>`` 의 account_id 스코핑 / fail-closed 테스트.

``bot positions`` 는 ``bots`` 테이블의 ``account_id`` 를 읽어
``TradeService.get_positions(bot_id, account_id=...)`` 로 포지션 조회를 봇 계좌로
스코핑한다. account_id 가 생략되면 ``TradeService`` 가 all-account 조회로 동작해
같은 ``bot_id`` 의 타 계좌 stale/legacy 포지션이 섞일 수 있으므로:

- valid account_id 면 ``get_positions(bot_id, account_id=<acct>)`` 로 스코핑.
- invalid (None/""/"default"/형식 위반) 면 ``get_positions`` 를 호출하지 않고
  ``VALIDATION_ERROR`` 구조화 에러 + nonzero exit 으로 fail-closed 한다. 빈 성공
  응답(0 포지션과 구분 불가) 을 차단하기 위함이다.

harness 는 in-process ``CliRunner(mix_stderr=False)`` 로, ``open_cli_db`` 가 lazy
import 하는 ``ante.cli.db_context.Database`` 와 함수 내부 lazy import 되는
``ante.trade.service.TradeService`` / ``PositionHistory`` / ``TradeRecorder`` /
``PerformanceTracker`` 를 patch 한다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="pos-scope-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Positions Scope Master",
    status="active",
    scopes=[],
)


def _parse_json(stdout: str) -> dict:
    """CLI stdout 에서 JSON envelope 을 파싱한다.

    성공 envelope 은 ``json.dumps(indent=2)`` 로 multi-line 이고, error envelope
    (``fmt.error``) 은 single-line 이다. 전체 stdout 파싱을 우선 시도하고,
    실패하면 마지막 비어있지 않은 줄을 파싱한다.
    """
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.splitlines()[-1])


def _make_db(account_id_row: dict | None) -> MagicMock:
    """``open_cli_db`` 가 yield 하는 ``Database`` 대역.

    ``fetch_one("SELECT account_id FROM bots ...")`` 가 주어진 row 를 반환한다.
    """
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_one = AsyncMock(return_value=account_id_row)
    return db


def _invoke(args: list[str], *, db: MagicMock, trade_service: MagicMock):
    """auth 우회 + DB/TradeService patch 하에 CLI 를 호출한다."""
    runner = CliRunner(mix_stderr=False)

    def _auth_set(ctx):  # noqa: ANN001, ANN202
        ctx.obj = ctx.obj or {}
        ctx.obj["member"] = _MASTER

    # PositionHistory / TradeRecorder / PerformanceTracker 는 lifecycle 만
    # 충족하면 되므로 가벼운 mock 으로 대체한다 (실제 SQL 미수행).
    pos_history = MagicMock()
    pos_history.initialize = AsyncMock()
    recorder = MagicMock()
    recorder.initialize = AsyncMock()

    with (
        patch("ante.cli.main.authenticate_member", side_effect=_auth_set),
        patch("ante.cli.main.get_db_path", return_value="/tmp/unused-pos-scope.db"),
        patch("ante.cli.db_context.Database", MagicMock(return_value=db)),
        patch("ante.trade.position.PositionHistory", return_value=pos_history),
        patch("ante.trade.recorder.TradeRecorder", return_value=recorder),
        patch("ante.trade.performance.PerformanceTracker", return_value=MagicMock()),
        patch("ante.trade.service.TradeService", return_value=trade_service),
    ):
        return runner.invoke(cli, args)


class TestBotPositionsValidAccountScope:
    """valid account_id → ``get_positions(bot_id, account_id=...)`` 스코핑."""

    def test_positions_scoped_to_bot_account(self) -> None:
        db = _make_db({"account_id": "acc-a"})

        position = SimpleNamespace(
            symbol="AAA",
            quantity=1.0,
            avg_entry_price=100.0,
            realized_pnl=10.0,
        )
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[position])

        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-shared"],
            db=db,
            trade_service=trade_service,
        )

        assert result.exit_code == 0, (
            f"exit={result.exit_code}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        # 봇 계좌(acc-a) 로 스코핑된 호출 — account_id 전파 lock.
        trade_service.get_positions.assert_awaited_once_with(
            "bot-shared", account_id="acc-a"
        )
        payload = _parse_json(result.stdout)
        symbols = [p["symbol"] for p in payload["positions"]]
        assert symbols == ["AAA"], payload


class TestBotPositionsInvalidAccountFailClosed:
    """invalid account_id → ``get_positions`` 미호출 + ``VALIDATION_ERROR`` + exit 1."""

    def test_default_account_id_fails_closed(self) -> None:
        """bots row 의 account_id 가 fallback 예약어 ``"default"`` 면 거부."""
        db = _make_db({"account_id": "default"})

        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])

        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-shared"],
            db=db,
            trade_service=trade_service,
        )

        # get_positions 가 호출되지 않아야 한다 (빈 성공 응답 차단).
        trade_service.get_positions.assert_not_called()

        assert result.exit_code == 1, (
            f"exit={result.exit_code}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        assert "Traceback" not in result.stderr, result.stderr
        payload = _parse_json(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "VALIDATION_ERROR", payload
        # 빈 성공 응답이 새지 않아야 한다 (0 포지션과 구분 불가).
        assert "보유 포지션 없음" not in result.stdout, result.stdout

    def test_empty_account_id_fails_closed(self) -> None:
        """bots row 의 account_id 가 빈 문자열이어도 동일하게 거부."""
        db = _make_db({"account_id": ""})

        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])

        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-shared"],
            db=db,
            trade_service=trade_service,
        )

        trade_service.get_positions.assert_not_called()
        assert result.exit_code == 1, (
            f"exit={result.exit_code}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        payload = _parse_json(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "VALIDATION_ERROR", payload


class TestBotPositionsMissingBotPreserved:
    """미존재 bot 정규화 회귀 lock (#1810 형제 계약 유지)."""

    def test_missing_bot_returns_not_found(self) -> None:
        """bots row 부재 → ``BOT_NOT_FOUND`` + exit 1 (account 검증 이전)."""
        db = _make_db(None)

        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[])

        result = _invoke(
            ["--format", "json", "bot", "positions", "bot-missing"],
            db=db,
            trade_service=trade_service,
        )

        trade_service.get_positions.assert_not_called()
        assert result.exit_code == 1, (
            f"exit={result.exit_code}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        payload = _parse_json(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "BOT_NOT_FOUND", payload
