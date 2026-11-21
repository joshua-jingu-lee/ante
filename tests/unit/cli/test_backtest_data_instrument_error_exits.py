"""``backtest``·``data``·``instrument`` 명령의 실패 경로 특성 테스트 (#2664 PR ②).

세 파일의 에러 출구 30곳을 JSON·text 두 모드로 하나씩 지난다. 기대값은
리터럴이다. JSON은 stdout 전체를 사전으로, text는 stderr의 줄 전체를 비교한다.
경계는 안팎 짝으로 둔다(바깥 사례는 한 인자만 바꾼다).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_EXCHANGES = "AMEX, KRX, NASDAQ, NYSE, TEST"
_TIMEFRAMES = "1m, 5m, 15m, 1h, 1d"


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(args: list[str], *patches: Any) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args)


def _failing_db(message: str) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        raise RuntimeError(message)
        yield

    return _open


def _assert_json(result: Result, envelope: dict[str, str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == envelope
    assert result.stderr == ""


def _assert_text(result: Result, lines: list[str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.splitlines() == lines


def _envelope(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


class _Service:
    result: dict[str, Any] = {}
    error: Exception | None = None

    def __init__(self, data_path: str) -> None:
        self.data_path = data_path

    async def run_subprocess(self, config: dict[str, Any]) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return dict(self.result)


def _service(
    result: dict[str, Any] | None = None, error: Exception | None = None
) -> Any:
    service = type(
        "_PatchedService", (_Service,), {"result": result or {}, "error": error}
    )
    return patch("ante.backtest.service.BacktestService", new=service)


_RUN_RESULT = {
    "strategy_name": "s",
    "strategy_version": "1",
    "strategy": "s",
    "period": "2026-01-02~2026-01-30",
    "total_return_pct": 0.0,
    "total_trades": 0,
    "final_balance": 10_000_000.0,
    "result_path": "r.json",
    "metrics": {},
}


@pytest.fixture
def run_args(tmp_path: Path) -> Callable[..., list[str]]:
    strategy = tmp_path / "strategy.py"
    strategy.write_text("", encoding="utf-8")

    def _args(mode: str, *options: str) -> list[str]:
        return [
            "--format",
            mode,
            "backtest",
            "run",
            str(strategy),
            "--data-path",
            str(tmp_path / "data"),
            "--db-path",
            str(tmp_path / "b.db"),
            *options,
        ]

    return _args


_START_FORMAT = "시작일 형식이 올바르지 않습니다: '2026/01/02' (YYYY-MM-DD 형식 필요)"
_END_FORMAT = "종료일 형식이 올바르지 않습니다: '2026-1-30' (YYYY-MM-DD 형식 필요)"
_CALENDAR = "날짜 형식이 올바르지 않습니다: day is out of range for month"
_RANGE = "시작일(2026-01-30)이 종료일(2026-01-02) 이후입니다."
_BT_EXCHANGE = f"유효하지 않은 거래소: 'KOSPI'. 허용 값: {_EXCHANGES}"
_BT_TIMEFRAME = f"유효하지 않은 타임프레임: '7x'. 허용 값: {_TIMEFRAMES}"
_BT_EMPTY_SYMBOL = (
    "유효하지 않은 종목 코드: '005930,'. 빈 종목 코드를 포함할 수 없습니다."
)
_BT_KRX_SYMBOL = (
    "유효하지 않은 종목 코드: 'ABC'. KRX 종목 코드는 6자리 숫자여야 합니다."
)
_BT_NO_DATA = "명시한 종목의 데이터가 없습니다(row_count=0): ['005930']"

_BACKTEST_REJECTED = [
    pytest.param(
        ["--start", "2026/01/02", "--end", "2026-01-30"],
        "INVALID_DATE",
        _START_FORMAT,
        id="start-format",
    ),
    pytest.param(
        ["--start", "2026-01-02", "--end", "2026-1-30"],
        "INVALID_DATE",
        _END_FORMAT,
        id="end-format",
    ),
    pytest.param(
        ["--start", "2026-02-30", "--end", "2026-03-02"],
        "INVALID_DATE",
        _CALENDAR,
        id="calendar",
    ),
    pytest.param(
        ["--start", "2026-01-30", "--end", "2026-01-02"],
        "INVALID_DATE_RANGE",
        _RANGE,
        id="inverted-range",
    ),
    pytest.param(
        ["--start", "2026-01-02", "--end", "2026-01-30", "--exchange", "KOSPI"],
        "BACKTEST_INVALID_EXCHANGE",
        _BT_EXCHANGE,
        id="exchange",
    ),
    pytest.param(
        ["--start", "2026-01-02", "--end", "2026-01-30", "--timeframe", "7x"],
        "BACKTEST_INVALID_TIMEFRAME",
        _BT_TIMEFRAME,
        id="timeframe",
    ),
    pytest.param(
        ["--start", "2026-01-02", "--end", "2026-01-30", "--symbols", "005930,"],
        "BACKTEST_INVALID_SYMBOL",
        _BT_EMPTY_SYMBOL,
        id="empty-symbol",
    ),
    pytest.param(
        ["--start", "2026-01-02", "--end", "2026-01-30", "--symbols", "ABC"],
        "BACKTEST_INVALID_SYMBOL",
        _BT_KRX_SYMBOL,
        id="krx-symbol",
    ),
]


class TestBacktestRunValidation:
    @pytest.mark.parametrize(("options", "code", "message"), _BACKTEST_REJECTED)
    def test_rejected_json(
        self,
        run_args: Callable[..., list[str]],
        options: list[str],
        code: str,
        message: str,
    ) -> None:
        result = _invoke(run_args("json", *options))
        _assert_json(result, _envelope(code, message))

    @pytest.mark.parametrize(("options", "code", "message"), _BACKTEST_REJECTED)
    def test_rejected_text(
        self,
        run_args: Callable[..., list[str]],
        options: list[str],
        code: str,
        message: str,
    ) -> None:
        result = _invoke(run_args("text", *options))
        _assert_text(result, [f"Error: {message}"])

    def test_same_day_range_is_accepted(
        self, run_args: Callable[..., list[str]]
    ) -> None:
        result = _invoke(
            run_args("json", "--start", "2026-01-02", "--end", "2026-01-02"),
            _service(result=_RUN_RESULT),
            patch(
                "ante.cli.commands.backtest._save_backtest_run",
                new=AsyncMock(return_value="run-1"),
            ),
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)["run_id"] == "run-1"

    def test_non_krx_symbol_shape_is_accepted(
        self, run_args: Callable[..., list[str]]
    ) -> None:
        result = _invoke(
            run_args(
                "json",
                "--start",
                "2026-01-02",
                "--end",
                "2026-01-30",
                "--exchange",
                "NYSE",
                "--symbols",
                "ABC",
            ),
            _service(result=_RUN_RESULT),
            patch(
                "ante.cli.commands.backtest._save_backtest_run",
                new=AsyncMock(return_value="run-2"),
            ),
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)["run_id"] == "run-2"


_RANGE_OPTIONS = ["--start", "2026-01-02", "--end", "2026-01-30"]


class TestBacktestRunExecution:
    def test_data_not_found_json(self, run_args: Callable[..., list[str]]) -> None:
        result = _invoke(
            run_args("json", *_RANGE_OPTIONS, "--symbols", "005930"),
            _service(result={**_RUN_RESULT, "datasets": [{"row_count": 0}]}),
        )
        _assert_json(result, _envelope("BACKTEST_DATA_NOT_FOUND", _BT_NO_DATA))

    def test_data_not_found_text(self, run_args: Callable[..., list[str]]) -> None:
        result = _invoke(
            run_args("text", *_RANGE_OPTIONS, "--symbols", "005930"),
            _service(result={**_RUN_RESULT, "datasets": [{"row_count": 0}]}),
        )
        _assert_text(result, [f"Error: {_BT_NO_DATA}"])

    def test_data_with_rows_is_accepted(
        self, run_args: Callable[..., list[str]]
    ) -> None:
        result = _invoke(
            run_args("json", *_RANGE_OPTIONS, "--symbols", "005930"),
            _service(result={**_RUN_RESULT, "datasets": [{"row_count": 1}]}),
            patch(
                "ante.cli.commands.backtest._save_backtest_run",
                new=AsyncMock(return_value="run-3"),
            ),
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)["run_id"] == "run-3"

    def test_service_failure_json(self, run_args: Callable[..., list[str]]) -> None:
        result = _invoke(
            run_args("json", *_RANGE_OPTIONS),
            _service(error=RuntimeError("백테스트 하위 프로세스 실패")),
        )
        _assert_json(result, _envelope("BACKTEST_ERROR", "백테스트 하위 프로세스 실패"))

    def test_service_failure_text(self, run_args: Callable[..., list[str]]) -> None:
        result = _invoke(
            run_args("text", *_RANGE_OPTIONS),
            _service(error=RuntimeError("백테스트 하위 프로세스 실패")),
        )
        _assert_text(result, ["Error: 백테스트 하위 프로세스 실패"])


class TestBacktestHistory:
    def _args(self, mode: str) -> list[str]:
        return ["--format", mode, "backtest", "history", "s-hist", "--limit", "7"]

    def _db(self) -> Any:
        return patch(
            "ante.cli.commands.backtest.open_cli_db",
            new=_failing_db("백테스트 이력 조회 실패"),
        )

    def test_lookup_failure_json(self) -> None:
        result = _invoke(self._args("json"), self._db())
        _assert_json(result, _envelope("BACKTEST_ERROR", "백테스트 이력 조회 실패"))

    def test_lookup_failure_text(self) -> None:
        result = _invoke(self._args("text"), self._db())
        _assert_text(result, ["Error: 백테스트 이력 조회 실패"])


_FILTER_TIMEFRAME = "허용되지 않은 timeframe 값: 7x (허용: 1m, 5m, 15m, 1h, 1d)"
_FILTER_FUNDAMENTAL = (
    "fundamental 데이터셋에는 timeframe 필터를 적용할 수 없습니다 "
    "(timeframe은 OHLCV 전용)"
)
_DATASET_ID_SHAPE = "dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다"
_DATASET_MISSING = "데이터셋을 찾을 수 없습니다"


@pytest.fixture
def data_path(tmp_path: Path) -> str:
    path = tmp_path / "data"
    path.mkdir()
    return str(path)


class TestDataList:
    @pytest.mark.parametrize(
        ("options", "message"),
        [
            pytest.param(["--timeframe", "7x"], _FILTER_TIMEFRAME, id="timeframe"),
            pytest.param(
                ["--type", "fundamental", "--timeframe", "1d"],
                _FILTER_FUNDAMENTAL,
                id="fundamental-timeframe",
            ),
        ],
    )
    def test_invalid_filter(
        self, data_path: str, options: list[str], message: str
    ) -> None:
        base = ["data", "list", "--data-path", data_path, *options]
        _assert_json(
            _invoke(["--format", "json", *base]),
            _envelope("DATA_INVALID_FILTER", message),
        )
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])

    def test_ohlcv_timeframe_is_accepted(self, data_path: str) -> None:
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "list",
                "--data-path",
                data_path,
                "--type",
                "ohlcv",
                "--timeframe",
                "1d",
            ]
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout) == {"datasets": [], "count": 0}

    def test_enrich_failure(self, data_path: str) -> None:
        listing = patch(
            "ante.data.datasets.list_datasets",
            return_value={"items": [{"symbol": "005930"}], "total": 1},
        )
        db = patch(
            "ante.cli.commands.data.open_cli_db",
            new=_failing_db("종목명 조회 실패"),
        )
        base = ["data", "list", "--data-path", data_path, "--symbol", "005930"]
        _assert_json(
            _invoke(["--format", "json", *base], listing, db),
            _envelope("DATA_ERROR", "종목명 조회 실패"),
        )
        _assert_text(
            _invoke(["--format", "text", *base], listing, db),
            ["Error: 종목명 조회 실패"],
        )


class TestDataInfo:
    @pytest.mark.parametrize(
        ("dataset_id", "code", "message"),
        [
            pytest.param(
                "005930", "DATA_INVALID_DATASET_ID", _DATASET_ID_SHAPE, id="shape"
            ),
            pytest.param(
                "005930__1d", "DATASET_NOT_FOUND", _DATASET_MISSING, id="missing"
            ),
        ],
    )
    def test_rejected(
        self, data_path: str, dataset_id: str, code: str, message: str
    ) -> None:
        base = ["data", "info", dataset_id, "--data-path", data_path]
        _assert_json(_invoke(["--format", "json", *base]), _envelope(code, message))
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])


_CONFIRM = "위험 명령입니다. --yes를 명시해야 데이터셋을 삭제합니다."
_TYPE_MISMATCH = (
    "data_type='fundamental'가 dataset_id에서 파생된 유형 'ohlcv'와 일치하지 않습니다"
)


class TestDataDelete:
    def test_confirmation_required(self, data_path: str) -> None:
        base = ["data", "delete", "005930__1d", "--data-path", data_path]
        _assert_json(
            _invoke(["--format", "json", *base]),
            _envelope("CLI_CONFIRMATION_REQUIRED", _CONFIRM),
        )
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {_CONFIRM}"])

    @pytest.mark.parametrize(
        ("options", "code", "message"),
        [
            pytest.param(
                ["005930"], "DATA_INVALID_DATASET_ID", _DATASET_ID_SHAPE, id="shape"
            ),
            pytest.param(
                ["005930__1d", "--type", "fundamental"],
                "DATA_INVALID_DATASET_ID",
                _TYPE_MISMATCH,
                id="type-mismatch",
            ),
            pytest.param(
                ["005930__1d"], "DATASET_NOT_FOUND", _DATASET_MISSING, id="missing"
            ),
        ],
    )
    def test_rejected(
        self, data_path: str, options: list[str], code: str, message: str
    ) -> None:
        base = ["data", "delete", *options, "--yes", "--data-path", data_path]
        _assert_json(_invoke(["--format", "json", *base]), _envelope(code, message))
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])


_VALIDATE_TIMEFRAME = f"유효하지 않은 타임프레임: '7x'. 허용 값: {_TIMEFRAMES}"
_VALIDATE_SYMBOL = "유효하지 않은 종목 코드: 'ABC' (KRX 6자리 숫자)"


class TestDataValidate:
    @pytest.mark.parametrize(
        ("options", "code", "message"),
        [
            pytest.param(
                ["--timeframe", "7x"],
                "DATA_VALIDATE_INVALID_TIMEFRAME",
                _VALIDATE_TIMEFRAME,
                id="timeframe",
            ),
            pytest.param(
                ["--symbol", "ABC"],
                "DATA_VALIDATE_INVALID_SYMBOL",
                _VALIDATE_SYMBOL,
                id="symbol",
            ),
        ],
    )
    def test_rejected(
        self, data_path: str, options: list[str], code: str, message: str
    ) -> None:
        base = ["data", "validate", "--data-path", data_path, *options]
        _assert_json(_invoke(["--format", "json", *base]), _envelope(code, message))
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])

    def test_valid_symbol_is_accepted(self, data_path: str) -> None:
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "validate",
                "--data-path",
                data_path,
                "--symbol",
                "005930",
            ]
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)


_INST_EXCHANGE = f"유효하지 않은 거래소: 'KOSPI'. 허용 값: {_EXCHANGES}"
_SYNC_UNSUPPORTED = (
    "거래소 'NYSE'는 canonical이나 현재 sync source(KIS domestic/KRX)가 "
    "미지원합니다 — invalid exchange 아님. sync 지원 거래소: KRX"
)


class TestInstrumentList:
    def test_invalid_exchange(self, tmp_path: Path) -> None:
        base = [
            "instrument",
            "list",
            "--exchange",
            "KOSPI",
            "--db-path",
            str(tmp_path / "i.db"),
        ]
        _assert_json(
            _invoke(["--format", "json", *base]),
            _envelope("INSTRUMENT_INVALID_EXCHANGE", _INST_EXCHANGE),
        )
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {_INST_EXCHANGE}"])


def _no_broker_config() -> Any:
    config = MagicMock()
    config.load.return_value.get.return_value = {}
    return patch("ante.config.Config", new=config)


class TestInstrumentSync:
    @pytest.mark.parametrize(
        ("exchange", "code", "message"),
        [
            pytest.param(
                "KOSPI", "INSTRUMENT_INVALID_EXCHANGE", _INST_EXCHANGE, id="invalid"
            ),
            pytest.param(
                "NYSE",
                "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED",
                _SYNC_UNSUPPORTED,
                id="unsupported",
            ),
        ],
    )
    def test_rejected(
        self, tmp_path: Path, exchange: str, code: str, message: str
    ) -> None:
        base = [
            "instrument",
            "sync",
            "--exchange",
            exchange,
            "--db-path",
            str(tmp_path / "i.db"),
        ]
        _assert_json(_invoke(["--format", "json", *base]), _envelope(code, message))
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])

    @pytest.mark.parametrize("mode", ["json", "text"])
    def test_missing_broker_config(self, tmp_path: Path, mode: str) -> None:
        result = _invoke(
            [
                "--format",
                mode,
                "instrument",
                "sync",
                "--db-path",
                str(tmp_path / "i.db"),
            ],
            _no_broker_config(),
        )
        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stdout == ""
        assert result.stderr.splitlines() == ["오류: 브로커 설정이 없습니다."]


_IMPORT_FORMAT = "지원하지 않는 파일 형식: .txt (csv 또는 json만 지원)"
_IMPORT_IO = "파일 읽기 실패: Expecting value: line 1 column 1 (char 0)"
_IMPORT_SHAPE = "JSON 파일은 배열 형태여야 합니다."
_IMPORT_EMPTY = "파일에 데이터가 없습니다."
_IMPORT_COLUMNS = "필수 컬럼 누락: symbol, exchange가 필요합니다."
_IMPORT_ROW_EXCHANGE = (
    f"유효하지 않은 거래소: 'KOSPI' (행 2, symbol='000660'). 허용 값: {_EXCHANGES}"
)
_IMPORT_ROW_SYMBOL = (
    "유효하지 않은 종목 코드: 'ABC' (행 2, exchange='KRX', KRX 6자리 숫자)."
)

_ROW_OK = {"symbol": "005930", "exchange": "KRX"}

_IMPORT_REJECTED = [
    pytest.param(
        "i.txt",
        "symbol,exchange\n",
        "INSTRUMENT_INVALID_FILE_FORMAT",
        _IMPORT_FORMAT,
        id="format",
    ),
    pytest.param("i.json", "", "INSTRUMENT_IO_ERROR", _IMPORT_IO, id="io"),
    pytest.param(
        "i.json", "{}", "INSTRUMENT_INVALID_JSON_SHAPE", _IMPORT_SHAPE, id="shape"
    ),
    pytest.param(
        "i.json", "[]", "INSTRUMENT_EMPTY_FILE", _IMPORT_EMPTY, id="empty-json"
    ),
    pytest.param(
        "i.csv",
        "symbol,exchange\n",
        "INSTRUMENT_EMPTY_FILE",
        _IMPORT_EMPTY,
        id="empty-csv",
    ),
    pytest.param(
        "i.json",
        json.dumps([{"symbol": "005930"}]),
        "INSTRUMENT_MISSING_COLUMNS",
        _IMPORT_COLUMNS,
        id="columns",
    ),
    pytest.param(
        "i.json",
        json.dumps([_ROW_OK, {"symbol": "000660", "exchange": "KOSPI"}]),
        "INSTRUMENT_INVALID_EXCHANGE",
        _IMPORT_ROW_EXCHANGE,
        id="row-exchange",
    ),
    pytest.param(
        "i.json",
        json.dumps([_ROW_OK, {"symbol": "ABC", "exchange": "KRX"}]),
        "INSTRUMENT_INVALID_SYMBOL",
        _IMPORT_ROW_SYMBOL,
        id="row-symbol",
    ),
]


class TestInstrumentImport:
    @pytest.mark.parametrize(("name", "content", "code", "message"), _IMPORT_REJECTED)
    def test_rejected(
        self, tmp_path: Path, name: str, content: str, code: str, message: str
    ) -> None:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        base = [
            "instrument",
            "import",
            str(path),
            "--dry-run",
            "--db-path",
            str(tmp_path / "i.db"),
        ]
        _assert_json(_invoke(["--format", "json", *base]), _envelope(code, message))
        _assert_text(_invoke(["--format", "text", *base]), [f"Error: {message}"])

    def test_non_krx_symbol_shape_is_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "i.json"
        path.write_text(
            json.dumps([_ROW_OK, {"symbol": "ABC", "exchange": "NYSE"}]),
            encoding="utf-8",
        )
        result = _invoke(
            [
                "--format",
                "json",
                "instrument",
                "import",
                str(path),
                "--dry-run",
                "--db-path",
                str(tmp_path / "i.db"),
            ]
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)["total"] == 2
