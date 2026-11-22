"""data 6개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. 데이터셋 조회·삭제
함수와 ``ParquetStore``의 조회 메서드를 대역으로 바꾸고, ``--data-path``를
명시해 설정 파일을 읽지 않는다. 여섯 명령은 IPC를 부르지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_DP = ["--data-path", "data"]

_ITEMS: list[dict[str, Any]] = [
    {
        "id": "005930__fundamental",
        "symbol": "005930",
        "timeframe": "",
        "data_type": "fundamental",
        "start_date": "2024-01-02",
        "end_date": "2025-12-30",
        "row_count": None,
        "file_size": None,
    },
    {
        "id": "005930__1d",
        "symbol": "005930",
        "timeframe": "1d",
        "data_type": "ohlcv",
        "start_date": "2024-01-02",
        "end_date": "2026-01-15",
        "row_count": None,
        "file_size": None,
    },
    {
        "id": "999999__1m",
        "symbol": "999999",
        "timeframe": "1m",
        "data_type": "ohlcv",
        "start_date": None,
        "end_date": None,
        "row_count": None,
        "file_size": None,
    },
]
_NAMES = {"005930": "삼성전자"}

_DETAIL_META: dict[str, Any] = {
    "id": "005930__1d",
    "symbol": "005930",
    "timeframe": "1d",
    "data_type": "ohlcv",
    "start_date": "2024-01-02",
    "end_date": "2026-01-15",
    "row_count": 500,
    "file_size": 12345,
}
_PREVIEW: list[dict[str, Any]] = [
    {"timestamp": "2024-01-02T00:00:00", "open": 70000.0, "close": 71000.0},
    {"timestamp": "2024-01-03T00:00:00", "open": 71000.0, "close": None},
]

_DELETED: dict[str, Any] = {
    "dataset_id": "005930__1d",
    "symbol": "005930",
    "timeframe": "1d",
    "data_type": "ohlcv",
    "path": "data/ohlcv/1d/005930",
    "deleted": True,
}


def _validated(symbol: str, total: int, corrupted: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": "1d",
        "total": total,
        "valid": total - corrupted,
        "corrupted": corrupted,
        "corrupted_files": [
            f"data/ohlcv/1d/{symbol}/2024-{i:02d}.parquet"
            for i in range(1, corrupted + 1)
        ],
    }


_VALIDATE_ROWS: dict[str, dict[str, Any]] = {
    "005930": _validated("005930", 3, 0),
    "000660": _validated("000660", 4, 2),
}

_LIST_FILTERS = [
    "--symbol",
    "005930",
    "--timeframe",
    "1d",
    "--type",
    "ohlcv",
    "--offset",
    "0",
    "--limit",
    "10",
]

_CASES: dict[str, list[str]] = {
    "list_empty": ["data", "list", *_DP],
    "list_page_past_end": ["data", "list", *_DP, "--offset", "100"],
    "list_rows": ["data", "list", *_DP],
    "list_filtered": ["data", "list", *_DP, *_LIST_FILTERS],
    "info_preview": ["data", "info", "005930__1d", *_DP],
    "info_no_preview": ["data", "info", "005930__1d", *_DP],
    "delete": ["data", "delete", "005930__1d", "--yes", *_DP],
    "delete_typed": ["data", "delete", "005930__1d", "--type", "ohlcv", "--yes", *_DP],
    "schema": ["data", "schema", *_DP],
    "storage_empty": ["data", "storage", *_DP],
    "storage_rows": ["data", "storage", *_DP],
    "validate_empty": ["data", "validate", *_DP],
    "validate_symbol_clean": ["data", "validate", "--symbol", "005930", *_DP],
    "validate_all": ["data", "validate", *_DP],
    "validate_fix": ["data", "validate", "--fix", *_DP],
    "validate_fix_clean": ["data", "validate", "--symbol", "005930", "--fix", *_DP],
}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _list_result(branch: str) -> dict[str, Any]:
    if branch == "list_empty":
        return {"items": [], "total": 0}
    if branch == "list_page_past_end":
        return {"items": [], "total": 3}
    if branch == "list_filtered":
        return {"items": [dict(_ITEMS[1])], "total": 1}
    return {"items": [dict(item) for item in _ITEMS], "total": 3}


def _storage_usage(branch: str) -> dict[str, int]:
    if branch == "storage_empty":
        return {}
    return {"1d": 5_242_880, "1m": 157_286_400, "fundamental": 52_429}


def _symbols(branch: str) -> list[str]:
    if branch == "validate_empty":
        return []
    return ["005930", "000660"]


def _invoke_case(
    branch: str,
    mode: str,
    *,
    mix_stderr: bool = True,
    deleted: dict[str, Any] | None = None,
    validated: dict[str, dict[str, Any]] | None = None,
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    preview = list(_PREVIEW) if branch == "info_preview" else []
    detail = {"dataset": dict(_DETAIL_META), "preview": preview}
    rows = validated if validated is not None else _VALIDATE_ROWS

    def _validate(self: Any, symbol: str, timeframe: str, fix: bool = False) -> Any:
        return dict(rows[symbol])

    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.data.datasets.list_datasets", lambda *a, **k: _list_result(branch)),
            ("ante.data.datasets.get_dataset_detail", lambda *a, **k: detail),
            (
                "ante.data.datasets.delete_dataset",
                lambda *a, **k: dict(deleted if deleted is not None else _DELETED),
            ),
            (
                "ante.data.store.ParquetStore.get_storage_usage",
                lambda self: _storage_usage(branch),
            ),
            (
                "ante.data.store.ParquetStore.list_symbols",
                lambda self, *a, **k: _symbols(branch),
            ),
            ("ante.data.store.ParquetStore.validate", _validate),
            ("ante.cli.commands.data.open_cli_db", _open_cli_db),
            ("ante.instrument.service.InstrumentService.load_readonly", AsyncMock()),
            (
                "ante.instrument.service.InstrumentService.get_name",
                lambda self, symbol, exchange="KRX": _NAMES.get(symbol, ""),
            ),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_DATA_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("{'datasets': [], 'count': 0}\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "datasets": [],\n'
        '    "count": 0\n'
        "  }\n"
        "}\n"
    ),
    ("list_page_past_end", "text"): ("{'datasets': [], 'count': 3}\n"),
    ("list_page_past_end", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "datasets": [],\n'
        '    "count": 3\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "          id |       symbol |         name |    timeframe |    data_type |   s"
        "tart_date |     end_date\n"
        "------------------------------------------------------------------------------"
        "------------------------\n"
        "005930__fundamental |       005930 |         삼성전자 |              |  fundam"
        "ental |   2024-01-02 |   2025-12-30\n"
        "  005930__1d |       005930 |         삼성전자 |           1d |        ohlcv |"
        "   2024-01-02 |   2026-01-15\n"
        "  999999__1m |       999999 |              |           1m |        ohlcv |    "
        "     None |         None\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "datasets": [\n'
        "      {\n"
        '        "id": "005930__fundamental",\n'
        '        "symbol": "005930",\n'
        '        "timeframe": "",\n'
        '        "data_type": "fundamental",\n'
        '        "start_date": "2024-01-02",\n'
        '        "end_date": "2025-12-30",\n'
        '        "row_count": null,\n'
        '        "file_size": null,\n'
        '        "name": "삼성전자"\n'
        "      },\n"
        "      {\n"
        '        "id": "005930__1d",\n'
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "data_type": "ohlcv",\n'
        '        "start_date": "2024-01-02",\n'
        '        "end_date": "2026-01-15",\n'
        '        "row_count": null,\n'
        '        "file_size": null,\n'
        '        "name": "삼성전자"\n'
        "      },\n"
        "      {\n"
        '        "id": "999999__1m",\n'
        '        "symbol": "999999",\n'
        '        "timeframe": "1m",\n'
        '        "data_type": "ohlcv",\n'
        '        "start_date": null,\n'
        '        "end_date": null,\n'
        '        "row_count": null,\n'
        '        "file_size": null,\n'
        '        "name": ""\n'
        "      }\n"
        "    ],\n"
        '    "count": 3\n'
        "  }\n"
        "}\n"
    ),
    ("list_filtered", "text"): (
        "          id |       symbol |         name |    timeframe |    data_type |   s"
        "tart_date |     end_date\n"
        "------------------------------------------------------------------------------"
        "------------------------\n"
        "  005930__1d |       005930 |         삼성전자 |           1d |        ohlcv |"
        "   2024-01-02 |   2026-01-15\n"
    ),
    ("list_filtered", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "datasets": [\n'
        "      {\n"
        '        "id": "005930__1d",\n'
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "data_type": "ohlcv",\n'
        '        "start_date": "2024-01-02",\n'
        '        "end_date": "2026-01-15",\n'
        '        "row_count": null,\n'
        '        "file_size": null,\n'
        '        "name": "삼성전자"\n'
        "      }\n"
        "    ],\n"
        '    "count": 1\n'
        "  }\n"
        "}\n"
    ),
    ("info_preview", "text"): (
        "  id          : 005930__1d\n"
        "  symbol      : 005930\n"
        "  timeframe   : 1d\n"
        "  data_type   : ohlcv\n"
        "  start_date  : 2024-01-02\n"
        "  end_date    : 2026-01-15\n"
        "  row_count   : 500\n"
        "  file_size   : 12345\n"
        "\n"
        "  preview:\n"
        "    {'timestamp': '2024-01-02T00:00:00', 'open': 70000.0, 'close': 71000.0}\n"
        "    {'timestamp': '2024-01-03T00:00:00', 'open': 71000.0, 'close': None}\n"
    ),
    ("info_preview", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "dataset": {\n'
        '      "id": "005930__1d",\n'
        '      "symbol": "005930",\n'
        '      "timeframe": "1d",\n'
        '      "data_type": "ohlcv",\n'
        '      "start_date": "2024-01-02",\n'
        '      "end_date": "2026-01-15",\n'
        '      "row_count": 500,\n'
        '      "file_size": 12345\n'
        "    },\n"
        '    "preview": [\n'
        "      {\n"
        '        "timestamp": "2024-01-02T00:00:00",\n'
        '        "open": 70000.0,\n'
        '        "close": 71000.0\n'
        "      },\n"
        "      {\n"
        '        "timestamp": "2024-01-03T00:00:00",\n'
        '        "open": 71000.0,\n'
        '        "close": null\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("info_no_preview", "text"): (
        "  id          : 005930__1d\n"
        "  symbol      : 005930\n"
        "  timeframe   : 1d\n"
        "  data_type   : ohlcv\n"
        "  start_date  : 2024-01-02\n"
        "  end_date    : 2026-01-15\n"
        "  row_count   : 500\n"
        "  file_size   : 12345\n"
    ),
    ("info_no_preview", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "dataset": {\n'
        '      "id": "005930__1d",\n'
        '      "symbol": "005930",\n'
        '      "timeframe": "1d",\n'
        '      "data_type": "ohlcv",\n'
        '      "start_date": "2024-01-02",\n'
        '      "end_date": "2026-01-15",\n'
        '      "row_count": 500,\n'
        '      "file_size": 12345\n'
        "    },\n"
        '    "preview": []\n'
        "  }\n"
        "}\n"
    ),
    ("delete", "text"): ("데이터셋 삭제 완료: 005930__1d\n"),
    ("delete", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "dataset_id": "005930__1d",\n'
        '    "symbol": "005930",\n'
        '    "timeframe": "1d",\n'
        '    "data_type": "ohlcv",\n'
        '    "path": "data/ohlcv/1d/005930",\n'
        '    "deleted": true\n'
        "  }\n"
        "}\n"
    ),
    ("delete_typed", "text"): ("데이터셋 삭제 완료: 005930__1d\n"),
    ("delete_typed", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "dataset_id": "005930__1d",\n'
        '    "symbol": "005930",\n'
        '    "timeframe": "1d",\n'
        '    "data_type": "ohlcv",\n'
        '    "path": "data/ohlcv/1d/005930",\n'
        '    "deleted": true\n'
        "  }\n"
        "}\n"
    ),
    ("schema", "text"): (
        "{'timestamp': \"Datetime(time_unit='ns', time_zone=None)\", 'symbol': 'St"
        "ring', 'open': 'Float64', 'high': 'Float64', 'low': 'Float64', '"
        "close': 'Float64', 'volume': 'Int64', 'amount': 'Int64', 'source'"
        ": 'String'}\n"
    ),
    ("schema", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "timestamp": "Datetime(time_unit=\'ns\', time_zone=None)",\n'
        '    "symbol": "String",\n'
        '    "open": "Float64",\n'
        '    "high": "Float64",\n'
        '    "low": "Float64",\n'
        '    "close": "Float64",\n'
        '    "volume": "Int64",\n'
        '    "amount": "Int64",\n'
        '    "source": "String"\n'
        "  }\n"
        "}\n"
    ),
    ("storage_empty", "text"): ("Total: 0.0 MB\n"),
    ("storage_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "total_bytes": 0,\n'
        '    "total_mb": 0.0,\n'
        '    "by_timeframe": {}\n'
        "  }\n"
        "}\n"
    ),
    ("storage_rows", "text"): ("Total: 155.1 MB\n"),
    ("storage_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "total_bytes": 162581709,\n'
        '    "total_mb": 155.1,\n'
        '    "by_timeframe": {\n'
        '      "1d": 5.0,\n'
        '      "1m": 150.0,\n'
        '      "fundamental": 0.1\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("validate_empty", "text"): (
        "{'message': '검증할 데이터가 없습니다.', 'results': []}\n"
    ),
    ("validate_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "검증할 데이터가 없습니다.",\n'
        '    "results": []\n'
        "  }\n"
        "}\n"
    ),
    ("validate_symbol_clean", "text"): (
        "\n  검증 완료: 전체 3개 / 정상 3개 / 손상 0개\n"
    ),
    ("validate_symbol_clean", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "results": [\n'
        "      {\n"
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "total": 3,\n'
        '        "valid": 3,\n'
        '        "corrupted": 0,\n'
        '        "corrupted_files": []\n'
        "      }\n"
        "    ],\n"
        '    "summary": {\n'
        '      "total_files": 3,\n'
        '      "valid": 3,\n'
        '      "corrupted": 0,\n'
        '      "fixed": false\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("validate_all", "text"): (
        "  000660/1d: 4개 중 2개 손상\n"
        "    → data/ohlcv/1d/000660/2024-01.parquet\n"
        "    → data/ohlcv/1d/000660/2024-02.parquet\n"
        "\n"
        "  검증 완료: 전체 7개 / 정상 5개 / 손상 2개\n"
    ),
    ("validate_all", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "results": [\n'
        "      {\n"
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "total": 3,\n'
        '        "valid": 3,\n'
        '        "corrupted": 0,\n'
        '        "corrupted_files": []\n'
        "      },\n"
        "      {\n"
        '        "symbol": "000660",\n'
        '        "timeframe": "1d",\n'
        '        "total": 4,\n'
        '        "valid": 2,\n'
        '        "corrupted": 2,\n'
        '        "corrupted_files": [\n'
        '          "data/ohlcv/1d/000660/2024-01.parquet",\n'
        '          "data/ohlcv/1d/000660/2024-02.parquet"\n'
        "        ]\n"
        "      }\n"
        "    ],\n"
        '    "summary": {\n'
        '      "total_files": 7,\n'
        '      "valid": 5,\n'
        '      "corrupted": 2,\n'
        '      "fixed": false\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("validate_fix", "text"): (
        "  000660/1d: 4개 중 2개 손상\n"
        "    → data/ohlcv/1d/000660/2024-01.parquet\n"
        "    → data/ohlcv/1d/000660/2024-02.parquet\n"
        "\n"
        "  검증 완료: 전체 7개 / 정상 5개 / 손상 2개\n"
        "  손상 파일을 .corrupted로 이동 완료\n"
    ),
    ("validate_fix", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "results": [\n'
        "      {\n"
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "total": 3,\n'
        '        "valid": 3,\n'
        '        "corrupted": 0,\n'
        '        "corrupted_files": []\n'
        "      },\n"
        "      {\n"
        '        "symbol": "000660",\n'
        '        "timeframe": "1d",\n'
        '        "total": 4,\n'
        '        "valid": 2,\n'
        '        "corrupted": 2,\n'
        '        "corrupted_files": [\n'
        '          "data/ohlcv/1d/000660/2024-01.parquet",\n'
        '          "data/ohlcv/1d/000660/2024-02.parquet"\n'
        "        ]\n"
        "      }\n"
        "    ],\n"
        '    "summary": {\n'
        '      "total_files": 7,\n'
        '      "valid": 5,\n'
        '      "corrupted": 2,\n'
        '      "fixed": true\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("validate_fix_clean", "text"): ("\n  검증 완료: 전체 3개 / 정상 3개 / 손상 0개\n"),
    ("validate_fix_clean", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "results": [\n'
        "      {\n"
        '        "symbol": "005930",\n'
        '        "timeframe": "1d",\n'
        '        "total": 3,\n'
        '        "valid": 3,\n'
        '        "corrupted": 0,\n'
        '        "corrupted_files": []\n'
        "      }\n"
        "    ],\n"
        '    "summary": {\n'
        '      "total_files": 3,\n'
        '      "valid": 3,\n'
        '      "corrupted": 0,\n'
        '      "fixed": false\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
}


class TestDataOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_DATA_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_DATA_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _DATA_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _DATA_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""


_MARKER = "user-name-marker"


@pytest.mark.parametrize("mode", ["text", "json"])
def test_delete_path_appears_only_in_json_stdout(mode: str) -> None:
    """``delete``가 지운 디렉터리 경로(사용자 이름이 들 수 있다)는 JSON의
    stdout에 한 번 나가고 text에는 나가지 않으며 stderr에는 나가지 않는다."""
    deleted = {**_DELETED, "path": f"/home/{_MARKER}/data/ohlcv/1d/005930"}
    result, _ = _invoke_case("delete", mode, mix_stderr=False, deleted=deleted)
    assert result.exit_code == 0, result.output
    assert result.stdout.count(_MARKER) == (1 if mode == "json" else 0)
    assert _MARKER not in result.stderr


@pytest.mark.parametrize("mode", ["text", "json"])
def test_validate_corrupted_paths_appear_once_in_stdout(mode: str) -> None:
    """``validate``의 손상 파일 경로는 두 형식 모두 stdout에 파일마다 한 번
    나가고 stderr에는 나가지 않는다."""
    corrupted = _validated("000660", 4, 2)
    corrupted["corrupted_files"] = [
        f"/home/{_MARKER}/data/{name}" for name in ("a.parquet", "b.parquet")
    ]
    validated = {"005930": _validated("005930", 3, 0), "000660": corrupted}
    result, _ = _invoke_case(
        "validate_all", mode, mix_stderr=False, validated=validated
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.count(_MARKER) == 2
    assert _MARKER not in result.stderr
