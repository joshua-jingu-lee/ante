"""CLI inverted date range(시작일 > 종료일) 거부 매트릭스 (#1597).

오라클 A7 finding(#1597): 4개 read/report 명령 —
``audit list --from-date/--to-date``, ``trade list --from/--to``,
``treasury snapshot --from/--to``, ``report performance --period daily
--start/--end`` — 이 inverted date range를 non-zero가 아니라 exit 0 빈
결과로 처리하던 ingress drift를 닫는다. ``backtest run``
(``src/ante/cli/commands/backtest.py:72-77``)은 이미
``INVALID_DATE_RANGE`` + ``SystemExit(1)``로 거부 중이며, 본 테스트는
공유 헬퍼 ``reject_inverted_date_range``가 나머지 4곳에 동형으로 적용된
결과를 검증한다.

검증 축:

- invalid-range(from > to): exit 1 + ``INVALID_DATE_RANGE``, 서비스/async
  경로(``_run``/Database/AuditLogger.query/get_trades/treasury/
  ``_run_performance``) **미호출** mock 단정.
- 회귀(유효): from < to / from == to / 한쪽만 / 둘 다 미지정 → exit 0.
- #1593 회귀: ``report performance --period monthly --start ... --end ...``
  은 여전히 ``CLI_OPTION_CONFLICT`` (period-exclusive 먼저, INVALID_DATE_RANGE
  아님); ``--period daily --year`` 도 ``CLI_OPTION_CONFLICT``.
- 형식 invalid(``2026-13-32``)는 기존 click 표준 경로 보존(미변경).
- JSON + text 두 포맷.

Non-Goals: web audit/treasury sibling 위험(별도 follow-up), 4곳 date
파싱 통합 리팩터, 신규 에러코드 신설.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from tests.unit._async_test_utils import asyncio_run_returning

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


def _make_runner() -> CliRunner:
    """``mix_stderr=False`` runner. click 버전에 따라 fallback."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner.

    ``authenticate_member``와 ``_run_authenticate``를 모두 patch하여 실제
    DB 접근을 방지한다 (#1404 / ``test_cli_date_validation.py`` 패턴).
    """
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        def _set_member(ctx):  # noqa: ANN001
            ctx.ensure_object(dict)
            ctx.obj["member"] = _MOCK_MASTER

        with (
            patch("ante.cli.main.authenticate_member", side_effect=_set_member),
            patch("ante.cli.middleware._run_authenticate"),
        ):
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _stdout(result) -> str:
    """mix_stderr 분리 환경에서 stdout만 안전하게 추출."""
    try:
        return result.stdout
    except (ValueError, UnicodeDecodeError):
        return result.output


def _assert_invalid_date_range_json(result) -> None:
    """JSON 포맷 inverted-range 응답 공통 검증."""
    assert result.exit_code == 1
    payload = json.loads(_stdout(result))
    assert payload["status"] == "error"
    assert payload["code"] == "INVALID_DATE_RANGE"


# 각 명령의 invoke args (invalid range: from=2026-02-01 > to=2026-01-01).
_INVALID_CASES = {
    "audit": [
        "audit",
        "list",
        "--from-date",
        "2026-02-01",
        "--to-date",
        "2026-01-01",
    ],
    "trade": [
        "trade",
        "list",
        "--from",
        "2026-02-01",
        "--to",
        "2026-01-01",
    ],
    "treasury": [
        "treasury",
        "snapshot",
        "--from",
        "2026-02-01",
        "--to",
        "2026-01-01",
        "--account",
        "oracle-paper",
    ],
    "report": [
        "report",
        "performance",
        "--period",
        "daily",
        "--start",
        "2026-02-01",
        "--end",
        "2026-01-01",
    ],
}

# 각 명령의 async/service 진입점 — invalid-range 시 호출되면 안 됨.
_ASYNC_ENTRYPOINTS = {
    "audit": "ante.cli.commands.audit._run",
    "trade": "ante.cli.commands.trade._run",
    "treasury": "ante.cli.commands.treasury._run",
    "report": "ante.cli.commands.report.asyncio.run",
}


class TestInvertedRangeRejectedJson:
    """invalid range(from > to) → exit 1 + INVALID_DATE_RANGE (JSON)."""

    @pytest.mark.parametrize("cmd", list(_INVALID_CASES))
    def test_rejected_json(self, runner, cmd):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES[cmd]])
        _assert_invalid_date_range_json(result)
        mock_async.assert_not_called()

    @pytest.mark.parametrize("cmd", list(_INVALID_CASES))
    def test_rejected_text(self, runner, cmd):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            result = runner.invoke(cli, _INVALID_CASES[cmd])
        assert result.exit_code == 1
        mock_async.assert_not_called()


class TestInvertedRangeNoServiceTouch:
    """invalid range 시 Database/service 레이어 자체에 도달하지 않는다."""

    def test_audit_no_db_no_logger(self, runner):
        with (
            patch("ante.cli.commands.audit._run") as mock_run,
            patch("ante.core.database.Database") as mock_db,
            patch("ante.audit.AuditLogger") as mock_logger,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["audit"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_db.assert_not_called()
        mock_logger.assert_not_called()

    def test_trade_no_service_no_db(self, runner):
        with (
            patch("ante.cli.commands.trade._run") as mock_run,
            patch("ante.cli.commands.trade._create_trade_service") as mock_svc,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["trade"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_svc.assert_not_called()
        mock_db.assert_not_called()

    def test_treasury_no_service_no_db(self, runner):
        with (
            patch("ante.cli.commands.treasury._run") as mock_run,
            patch("ante.cli.commands.treasury._create_treasury") as mock_svc,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(
                cli, ["--format", "json", *_INVALID_CASES["treasury"]]
            )
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_svc.assert_not_called()
        mock_db.assert_not_called()

    def test_report_no_run_performance_no_db(self, runner):
        with (
            patch("ante.cli.commands.report.asyncio.run") as mock_run,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["report"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_db.assert_not_called()


class TestValidRangeRegression:
    """유효 조합은 회귀 없이 통과(서비스 진입 도달 — exit 0)."""

    @pytest.mark.parametrize(
        ("cmd", "args"),
        [
            (
                "audit",
                [
                    "audit",
                    "list",
                    "--from-date",
                    "2026-01-01",
                    "--to-date",
                    "2026-02-01",
                ],
            ),
            (
                "audit",
                [
                    "audit",
                    "list",
                    "--from-date",
                    "2026-01-15",
                    "--to-date",
                    "2026-01-15",
                ],
            ),
            (
                "audit",
                ["audit", "list", "--from-date", "2026-01-01"],
            ),
            (
                "audit",
                ["audit", "list", "--to-date", "2026-02-01"],
            ),
            (
                "audit",
                ["audit", "list"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-01", "--to", "2026-02-01"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-15", "--to", "2026-01-15"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-01"],
            ),
            (
                "trade",
                ["trade", "list"],
            ),
            (
                "report",
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-02-01",
                ],
            ),
            (
                "report",
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--start",
                    "2026-01-15",
                    "--end",
                    "2026-01-15",
                ],
            ),
            (
                "report",
                ["report", "performance", "--period", "daily", "--start", "2026-01-01"],
            ),
            (
                "report",
                ["report", "performance"],
            ),
        ],
    )
    def test_valid_passes_to_service(self, runner, cmd, args):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            mock_async.side_effect = asyncio_run_returning([])
            result = runner.invoke(cli, args)
        assert result.exit_code == 0, _stdout(result)
        mock_async.assert_called_once()

    @pytest.mark.parametrize(
        "args",
        [
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-01",
                "--to",
                "2026-02-01",
                "--account",
                "oracle-paper",
            ],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-15",
                "--to",
                "2026-01-15",
                "--account",
                "oracle-paper",
            ],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-01",
                "--account",
                "oracle-paper",
            ],
            ["treasury", "snapshot", "--account", "oracle-paper"],
        ],
    )
    def test_treasury_valid_passes_to_service(self, runner, args):
        with patch("ante.cli.commands.treasury._run") as mock_run:
            mock_run.side_effect = asyncio_run_returning(
                {
                    "account_id": "oracle-paper",
                    "snapshot_date": "2026-01-15",
                    "total_asset": 1.0,
                    "ante_eval_amount": 1.0,
                    "ante_purchase_amount": 1.0,
                    "unallocated": 0.0,
                }
            )
            result = runner.invoke(cli, ["--format", "json", *args])
        assert result.exit_code == 0, _stdout(result)
        mock_run.assert_called_once()


class TestRegression1593Preserved:
    """#1593 period-exclusive 우선순위/코드 보존(순서 엄수)."""

    def test_monthly_with_start_end_still_conflict(self, runner):
        """monthly + start/end → 여전히 CLI_OPTION_CONFLICT (INVALID_DATE_RANGE 아님).

        inverted(start>end)여도 period-exclusive 검증이 먼저이므로
        CLI_OPTION_CONFLICT로 거부되어야 한다.
        """
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-02-01",
                    "--end",
                    "2026-01-01",
                ],
            )
        assert result.exit_code == 1
        payload = json.loads(_stdout(result))
        assert payload["code"] == "CLI_OPTION_CONFLICT"
        assert payload["code"] != "INVALID_DATE_RANGE"
        mock_run.assert_not_called()

    def test_daily_with_year_still_conflict(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--year",
                    "2026",
                ],
            )
        assert result.exit_code == 1
        payload = json.loads(_stdout(result))
        assert payload["code"] == "CLI_OPTION_CONFLICT"
        mock_run.assert_not_called()


class TestFormatInvalidPathPreserved:
    """형식 invalid는 기존 click.BadParameter/UsageError 경로 보존(미변경)."""

    @pytest.mark.parametrize(
        "args",
        [
            ["audit", "list", "--from-date", "2026-13-32", "--to-date", "2026-01-01"],
            ["trade", "list", "--from", "2026-13-32", "--to", "2026-01-01"],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-13-32",
                "--to",
                "2026-01-01",
                "--account",
                "oracle-paper",
            ],
            [
                "report",
                "performance",
                "--period",
                "daily",
                "--start",
                "2026-13-32",
                "--end",
                "2026-01-01",
            ],
        ],
    )
    def test_format_invalid_not_invalid_date_range(self, runner, args):
        """형식 오류는 click 표준 경로 — INVALID_DATE_RANGE가 아니다.

        click ``BadParameter``는 exit 2 + text stderr이며, 본 헬퍼는
        ``validate_iso_date`` 거부 이후 도달하지 않는다.
        """
        result = runner.invoke(cli, args)
        assert result.exit_code != 0
        assert "INVALID_DATE_RANGE" not in result.output


# ──────────────────────────────────────────────────────────────────────────
# #2367: ``trade list --to <날짜>`` end-of-day 경계 (실제 DB seed + recorder
# SQL 실경로). ``--to D`` 가 ``T00:00:00`` (date-only ``fromisoformat``) 으로
# 들어가 당일 장중 거래가 ``timestamp <= ?`` 에서 전부 제외되던 회귀를 닫는다.
#
# 본 클래스는 위 inverted-range 매트릭스의 ``mock service`` 패턴과 달리
# **실제 ``Database`` seed + 실제 ``TradeService.get_trades`` SQL 실경로** 를
# 거친다 (mocked service 금지 — 경계 lexical 비교가 SQL 단계에서 검증돼야
# 한다). ``--config-dir <tmp>`` → ``get_db_path`` → ``<tmp>/db/ante.db`` 를
# 시드 DB 와 동일 경로로 가리키게 해 CLI 가 시드된 DB 를 그대로 읽는다.


async def _seed_trades_db(db_path: str, rows: list[dict]) -> None:
    """실제 ``Database`` 로 ``<tmp>/db/ante.db`` 에 trades 행을 직접 seed.

    ``TradeRecorder``/``PositionHistory`` 의 ``initialize()`` 로 schema 를
    부트스트랩한 뒤, 각 행을 raw SQL 로 INSERT 한다. ``timestamp`` 는
    호출자가 지정한 저장 문자열을 **그대로** 쓴다 (isoformat aware,
    공백 구분 포맷 등 저장 포맷별 lexical 경계를 그대로 검증하기 위함).
    """
    from ante.core.database import Database
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder

    db = Database(db_path)
    await db.connect()
    try:
        ph = PositionHistory(db)
        await ph.initialize()
        rec = TradeRecorder(db, ph)
        await rec.initialize()
        for row in rows:
            await db.execute(
                "INSERT INTO trades "
                "(trade_id, bot_id, strategy_id, symbol, side, quantity, price, "
                " status, order_type, reason, commission, timestamp, order_id, "
                " account_id, currency, exchange) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["trade_id"],
                    row.get("bot_id", "bot1"),
                    row.get("strategy_id", "s1"),
                    row.get("symbol", "005930"),
                    row.get("side", "buy"),
                    row.get("quantity", 10.0),
                    row.get("price", 50000.0),
                    row.get("status", "filled"),
                    row.get("order_type", "market"),
                    row.get("reason", "seed"),
                    row.get("commission", 0.0),
                    row["timestamp"],
                    row.get("order_id", row["trade_id"]),
                    row.get("account_id", "acc-real"),
                    row.get("currency", "KRW"),
                    row.get("exchange", "KRX"),
                ),
            )
    finally:
        await db.close()


async def _seed_adjustment_via_recorder(db_path: str, *, account_id: str) -> str:
    """실제 ``TradeRecorder.save_adjustment()`` 로 보정 행 1건을 생성하고 날짜 반환.

    #2371: 보정 행 timestamp 가 ``save_trade`` 와 동일한 UTC-aware isoformat 으로
    저장됨을 CLI 실경로로 검증하기 위해, raw INSERT 가 아니라 실제 서비스 메서드를
    경유한다. wall-clock 비결정(UTC 자정 경계)은 호출자가 **저장된 timestamp 에서
    날짜를 읽어** 동일 날짜로 조회하므로 제거된다. 저장 날짜(``YYYY-MM-DD``)를
    반환한다.
    """
    from ante.core.database import Database
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder

    db = Database(db_path)
    await db.connect()
    try:
        ph = PositionHistory(db)
        await ph.initialize()
        rec = TradeRecorder(db, ph)
        await rec.initialize()
        await rec.save_adjustment(
            bot_id="bot1",
            symbol="005930",
            old_quantity=10.0,
            new_quantity=15.0,
            reason="broker mismatch",
            account_id=account_id,
        )
        row = await db.fetch_one(
            "SELECT timestamp FROM trades WHERE status = 'adjusted'"
        )
        assert row is not None
        ts: str = row["timestamp"]
        # 저장 날짜(달력일)만 추출 — isoformat 의 'T' 앞 날짜 부분.
        return ts[:10]
    finally:
        await db.close()


def _trade_list_ids(runner, tmp_path, *cli_args: str) -> list[str]:
    """``trade list --format json`` 을 실제 시드 DB 에 대해 실행, trade_id 집합 반환.

    ``--config-dir <tmp_path>`` 로 시드 DB(``<tmp_path>/db/ante.db``) 를
    가리키고, 실제 ``TradeService.get_trades`` SQL 경로를 거친다 (mock 없음).
    CliRunner 가 동기 경계에서 내부적으로 ``asyncio.run`` 을 호출하므로 본
    헬퍼는 await 없이 동기로 호출된다.
    """
    result = runner.invoke(
        cli,
        [
            "--config-dir",
            str(tmp_path),
            "--format",
            "json",
            "trade",
            "list",
            "--limit",
            "50",
            *cli_args,
        ],
    )
    assert result.exit_code == 0, _stdout(result)
    payload = json.loads(_stdout(result))
    trades = payload.get("trades", [])
    return [t["trade_id"] for t in trades]


@pytest.fixture
def _seed_db_path(tmp_path):
    """``<tmp_path>/db/ante.db`` 경로 (디렉토리 보장)."""
    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "ante.db")


class TestTradeListToEndOfDayBoundary:
    """#2367: ``--to D`` 가 당일 end-of-day(``23:59:59.999999+00:00``) 포함 경계."""

    def test_same_day_intraday_isoformat_row_returned(
        self, runner, tmp_path, _seed_db_path
    ):
        """isoformat 장중 행(``2026-06-12T04:43:53+00:00``)이 동일-날짜 범위에 포함.

        수정 전(main): ``--to 2026-06-12`` → ``T00:00:00`` 상한 → 장중 행이
        ``timestamp <= ?`` 에서 제외돼 **빈 결과(RED)**. 수정 후: end-of-day
        상한으로 포함(GREEN).
        """
        asyncio.run(
            _seed_trades_db(
                _seed_db_path,
                [
                    {
                        "trade_id": "11111111-1111-1111-1111-111111111111",
                        "timestamp": "2026-06-12T04:43:53+00:00",
                    }
                ],
            )
        )
        ids = _trade_list_ids(
            runner, tmp_path, "--from", "2026-06-12", "--to", "2026-06-12"
        )
        assert ids == ["11111111-1111-1111-1111-111111111111"], (
            f"동일-날짜 범위에 장중 isoformat 행이 포함돼야 한다. ids={ids}"
        )

    def test_end_of_day_boundary_row_included(self, runner, tmp_path, _seed_db_path):
        """당일 ``23:59:59.999999+00:00`` 행 포함 (naive ``time.max`` 반례).

        ``--to`` 상한이 UTC-aware ``23:59:59.999999+00:00`` 여야 동일 포맷의
        당일 마지막 microsecond 행이 equal 포함된다. 만약 상한이 naive
        ``time.max`` (``...T23:59:59.999999`` tz 없음)였다면 aware 저장값과의
        lexical 비교에서 제외되는 반례 — 본 케이스가 그 회귀를 고정한다.
        """
        asyncio.run(
            _seed_trades_db(
                _seed_db_path,
                [
                    {
                        "trade_id": "22222222-2222-2222-2222-222222222222",
                        "timestamp": "2026-06-12T23:59:59.999999+00:00",
                    }
                ],
            )
        )
        ids = _trade_list_ids(
            runner, tmp_path, "--from", "2026-06-12", "--to", "2026-06-12"
        )
        assert ids == ["22222222-2222-2222-2222-222222222222"], (
            f"당일 end-of-day microsecond 경계 행이 포함돼야 한다. ids={ids}"
        )

    def test_next_day_midnight_row_excluded(self, runner, tmp_path, _seed_db_path):
        """다음날 자정 ``2026-06-13T00:00:00+00:00`` 행은 ``--to 2026-06-12`` 제외."""
        asyncio.run(
            _seed_trades_db(
                _seed_db_path,
                [
                    {
                        "trade_id": "33333333-3333-3333-3333-333333333333",
                        "timestamp": "2026-06-12T10:00:00+00:00",
                    },
                    {
                        "trade_id": "44444444-4444-4444-4444-444444444444",
                        "timestamp": "2026-06-13T00:00:00+00:00",
                    },
                ],
            )
        )
        ids = _trade_list_ids(
            runner, tmp_path, "--from", "2026-06-12", "--to", "2026-06-12"
        )
        assert ids == ["33333333-3333-3333-3333-333333333333"], (
            f"다음날 자정 행은 제외, 당일 행만 포함돼야 한다. ids={ids}"
        )

    def test_adjustment_row_included_in_to_only_query(
        self, runner, tmp_path, _seed_db_path
    ):
        """#2371: 실 ``save_adjustment()`` 보정 행이 ``--to D``(from 미지정)에 포함.

        보정 행은 ``save_trade`` 와 동일한 UTC-aware isoformat 으로 저장된다.
        wall-clock 비결정(UTC 자정 경계)은 **저장된 timestamp 의 날짜를 읽어**
        그 날짜로 ``--to`` 상한(``...T23:59:59.999999+00:00``)을 지정해 제거한다.
        """
        adj_date = asyncio.run(
            _seed_adjustment_via_recorder(_seed_db_path, account_id="acc-real")
        )
        ids = _trade_list_ids(runner, tmp_path, "--to", adj_date)
        assert len(ids) == 1, (
            f"보정 행이 --to {adj_date} 쿼리에 포함돼야 한다. ids={ids}"
        )

    def test_adjustment_row_included_when_from_specified(
        self, runner, tmp_path, _seed_db_path
    ):
        """#2371: 실 ``save_adjustment()`` 보정 행이 ``--from D`` 당일 경계에 포함.

        #2370 의 known-limitation(공백 포맷 행이 ``--from`` 당일 ``T00:00:00``
        하한에서 lexical 제외)을 해소한다. 보정 행이 isoformat UTC 로 저장되므로
        당일 ``--from``/``--to`` 동일 날짜 조회에 포함된다(**main RED**: 공백 포맷이라
        제외). wall-clock 비결정은 저장 날짜를 읽어 동일 날짜로 조회해 제거한다.
        """
        adj_date = asyncio.run(
            _seed_adjustment_via_recorder(_seed_db_path, account_id="acc-real")
        )
        ids = _trade_list_ids(runner, tmp_path, "--from", adj_date, "--to", adj_date)
        assert len(ids) == 1, (
            f"보정 행이 --from/--to {adj_date} 당일 경계에 포함돼야 한다. ids={ids}"
        )

    def test_from_only_returns_same_day_intraday(self, runner, tmp_path, _seed_db_path):
        """``--from`` 만 지정 시 당일 장중 isoformat 행 반환(기존 동작 보존)."""
        asyncio.run(
            _seed_trades_db(
                _seed_db_path,
                [
                    {
                        "trade_id": "77777777-7777-7777-7777-777777777777",
                        "timestamp": "2026-06-12T04:43:53+00:00",
                    }
                ],
            )
        )
        ids = _trade_list_ids(runner, tmp_path, "--from", "2026-06-12")
        assert ids == ["77777777-7777-7777-7777-777777777777"], (
            f"--from-only 는 당일 장중 행을 반환해야 한다. ids={ids}"
        )

    def test_to_next_day_includes_same_day_intraday(
        self, runner, tmp_path, _seed_db_path
    ):
        """``--to`` 를 다음날로 밀면 당일 장중 행 포함(기존 동작 보존)."""
        asyncio.run(
            _seed_trades_db(
                _seed_db_path,
                [
                    {
                        "trade_id": "88888888-8888-8888-8888-888888888888",
                        "timestamp": "2026-06-12T04:43:53+00:00",
                    }
                ],
            )
        )
        ids = _trade_list_ids(
            runner, tmp_path, "--from", "2026-06-12", "--to", "2026-06-13"
        )
        assert ids == ["88888888-8888-8888-8888-888888888888"], (
            f"--to 다음날 범위에 당일 장중 행이 포함돼야 한다. ids={ids}"
        )
