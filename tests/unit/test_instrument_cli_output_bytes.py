"""instrument 4개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``import``의 입력
파일은 작업 디렉터리(임시 디렉터리)에 상대 경로로 만든다. ``sync``는 브로커
어댑터를 대역으로 바꾼다. 네 명령은 IPC를 부르지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.instrument.models import Instrument
from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_LIST_ROWS: list[dict[str, Any]] = [
    {
        "symbol": "005930",
        "name": "삼성전자",
        "name_en": "Samsung Electronics",
        "instrument_type": "stock",
        "listed": 1,
    },
    {
        "symbol": "069500",
        "name": None,
        "name_en": None,
        "instrument_type": None,
        "listed": 0,
    },
]

_SEARCH_HITS = [
    Instrument(
        symbol="005930",
        exchange="KRX",
        name="삼성전자",
        name_en="Samsung Electronics",
        instrument_type="stock",
    ),
    Instrument(symbol="005935", exchange="KRX", name="삼성전자우"),
]

_BROKER_CONFIG = {
    "app_key": "FAKE-APP-KEY-0000",
    "app_secret": "FAKE-APP-SECRET-0000",
    "account_no": "FAKE-ACCOUNT-NO-0000",
}

_SYNC_OLD_ROWS = [
    {"symbol": "005930", "listed": 1},
    {"symbol": "000020", "listed": 1},
    {"symbol": "000030", "listed": 0},
]
_SYNC_RAW = [
    {"symbol": "005930", "name": "삼성전자", "instrument_type": "stock"},
    {"symbol": "000660", "name": "SK하이닉스", "name_en": "SK hynix"},
    {"symbol": "069500", "name": "KODEX 200", "instrument_type": "etf"},
]

_CSV_HEADER = "symbol,exchange,name,name_en,instrument_type,listed\n"
_CSV_ROWS = [
    "005930,KRX,삼성전자,Samsung Electronics,stock,true\n",
    "000660,KRX,SK하이닉스,SK hynix,stock,1\n",
]
_JSON_RECORDS: list[dict[str, Any]] = [
    {"symbol": "005930", "exchange": "KRX", "name": "삼성전자"},
    {"symbol": "AAPL", "exchange": "NASDAQ", "instrument_type": "stock"},
]


def _prepare_files(root: Path) -> None:
    (root / "inst.csv").write_text(_CSV_HEADER + "".join(_CSV_ROWS), encoding="utf-8")
    (root / "inst.json").write_text(json.dumps(_JSON_RECORDS), encoding="utf-8")
    many = [f"{i:06d},KRX,종목{i},,stock,y\n" for i in range(1, 12)]
    (root / "many.csv").write_text(_CSV_HEADER + "".join(many), encoding="utf-8")


_CASES: dict[str, list[str]] = {
    "list_empty": ["instrument", "list"],
    "list_rows": ["instrument", "list"],
    "list_filtered": [
        "instrument",
        "list",
        "--exchange",
        "KRX",
        "--type",
        "etf",
        "--listed-only",
    ],
    "search_empty": ["instrument", "search", "없는종목"],
    "search_rows": ["instrument", "search", "삼성", "--limit", "5", "--listed-only"],
    "sync": ["instrument", "sync"],
    "import_csv": ["instrument", "import", "inst.csv"],
    "import_json": ["instrument", "import", "inst.json"],
    "import_dry_run_csv": ["instrument", "import", "inst.csv", "--dry-run"],
    "import_dry_run_json": ["instrument", "import", "inst.json", "--dry-run"],
    "import_dry_run_many": ["instrument", "import", "many.csv", "--dry-run"],
}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


@pytest.fixture(autouse=True)
def _workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_files(tmp_path)


def _fake_db(branch: str) -> AsyncMock:
    db = AsyncMock()
    if branch.startswith("list_"):
        rows = [] if branch == "list_empty" else list(_LIST_ROWS)
        db.fetch_all = AsyncMock(return_value=rows)
    else:
        db.fetch_all = AsyncMock(return_value=list(_SYNC_OLD_ROWS))
    return db


class _FakeAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def get_instruments(self, exchange: str) -> list[dict[str, Any]]:
        return [dict(item) for item in _SYNC_RAW]


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True, args: list[str] | None = None
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    db = _fake_db(branch)

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield db

    hits = [] if branch == "search_empty" else list(_SEARCH_HITS)
    config = SimpleNamespace(
        get=lambda key, default=None: (
            dict(_BROKER_CONFIG) if key == "broker" else default
        )
    )

    async def _bulk_upsert(self: Any, instruments: list[Instrument]) -> int:
        return len(instruments)

    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    case_args = list(args if args is not None else _CASES[branch])
    full_args = ["--format", "json", *case_args] if mode == "json" else case_args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.instrument.open_cli_db", _open_cli_db),
            ("ante.instrument.service.InstrumentService.initialize", AsyncMock()),
            (
                "ante.instrument.service.InstrumentService.search",
                AsyncMock(return_value=hits),
            ),
            ("ante.instrument.service.InstrumentService.bulk_upsert", _bulk_upsert),
            ("ante.config.Config.load", lambda **_: config),
            ("ante.broker.kis.KISAdapter", _FakeAdapter),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_INSTRUMENT_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("{'instruments': [], 'count': 0}\n"),
    ("list_empty", "json"): ('{\n  "instruments": [],\n  "count": 0\n}\n'),
    ("list_rows", "text"): (
        "      symbol |         name |      name_en |         type |       listed\n"
        "------------------------------------------------------------------------\n"
        "      005930 |         삼성전자 | Samsung Electronics |        stock |        "
        "    Y\n"
        "      069500 |              |              |              |            N\n"
    ),
    ("list_rows", "json"): (
        "[\n"
        "  {\n"
        '    "symbol": "005930",\n'
        '    "name": "삼성전자",\n'
        '    "name_en": "Samsung Electronics",\n'
        '    "type": "stock",\n'
        '    "listed": "Y"\n'
        "  },\n"
        "  {\n"
        '    "symbol": "069500",\n'
        '    "name": "",\n'
        '    "name_en": "",\n'
        '    "type": "",\n'
        '    "listed": "N"\n'
        "  }\n"
        "]\n"
    ),
    ("list_filtered", "text"): (
        "      symbol |         name |      name_en |         type |       listed\n"
        "------------------------------------------------------------------------\n"
        "      005930 |         삼성전자 | Samsung Electronics |        stock |        "
        "    Y\n"
        "      069500 |              |              |              |            N\n"
    ),
    ("list_filtered", "json"): (
        "[\n"
        "  {\n"
        '    "symbol": "005930",\n'
        '    "name": "삼성전자",\n'
        '    "name_en": "Samsung Electronics",\n'
        '    "type": "stock",\n'
        '    "listed": "Y"\n'
        "  },\n"
        "  {\n"
        '    "symbol": "069500",\n'
        '    "name": "",\n'
        '    "name_en": "",\n'
        '    "type": "",\n'
        '    "listed": "N"\n'
        "  }\n"
        "]\n"
    ),
    ("search_empty", "text"): ("{'results': [], 'count': 0}\n"),
    ("search_empty", "json"): ('{\n  "results": [],\n  "count": 0\n}\n'),
    ("search_rows", "text"): (
        "      symbol |     exchange |         name |      name_en |         type\n"
        "------------------------------------------------------------------------\n"
        "      005930 |          KRX |         삼성전자 | Samsung Electronics |        "
        "stock\n"
        "      005935 |          KRX |        삼성전자우 |              |             "
        "\n"
    ),
    ("search_rows", "json"): (
        "[\n"
        "  {\n"
        '    "symbol": "005930",\n'
        '    "exchange": "KRX",\n'
        '    "name": "삼성전자",\n'
        '    "name_en": "Samsung Electronics",\n'
        '    "type": "stock"\n'
        "  },\n"
        "  {\n"
        '    "symbol": "005935",\n'
        '    "exchange": "KRX",\n'
        '    "name": "삼성전자우",\n'
        '    "name_en": "",\n'
        '    "type": ""\n'
        "  }\n"
        "]\n"
    ),
    ("sync", "text"): (
        "{'sync_result': {'total': 3, 'new': 2, 'updated': 1, 'delisted': 1}, 'message'"
        ": '동기화 완료: 신규 2건, 갱신 1건, 상폐 1건'}\n"
    ),
    ("sync", "json"): (
        "{\n"
        '  "sync_result": {\n'
        '    "total": 3,\n'
        '    "new": 2,\n'
        '    "updated": 1,\n'
        '    "delisted": 1\n'
        "  },\n"
        '  "message": "동기화 완료: 신규 2건, 갱신 1건, 상폐 1건"\n'
        "}\n"
    ),
    ("import_csv", "text"): ("종목 import 완료: 2건\n"),
    ("import_csv", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "종목 import 완료: 2건",\n'
        '  "data": {\n'
        '    "count": 2,\n'
        '    "file": "inst.csv"\n'
        "  }\n"
        "}\n"
    ),
    ("import_json", "text"): ("종목 import 완료: 2건\n"),
    ("import_json", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "종목 import 완료: 2건",\n'
        '  "data": {\n'
        '    "count": 2,\n'
        '    "file": "inst.json"\n'
        "  }\n"
        "}\n"
    ),
    ("import_dry_run_csv", "text"): (
        "  미리보기 (2건 중 상위 2건):\n"
        "      symbol |     exchange |         name |         type\n"
        "---------------------------------------------------------\n"
        "      005930 |          KRX |         삼성전자 |        stock\n"
        "      000660 |          KRX |       SK하이닉스 |        stock\n"
    ),
    ("import_dry_run_csv", "json"): (
        "{\n"
        '  "dry_run": true,\n'
        '  "total": 2,\n'
        '  "preview": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "exchange": "KRX",\n'
        '      "name": "삼성전자",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000660",\n'
        '      "exchange": "KRX",\n'
        '      "name": "SK하이닉스",\n'
        '      "type": "stock"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("import_dry_run_json", "text"): (
        "  미리보기 (2건 중 상위 2건):\n"
        "      symbol |     exchange |         name |         type\n"
        "---------------------------------------------------------\n"
        "      005930 |          KRX |         삼성전자 |             \n"
        "        AAPL |       NASDAQ |              |        stock\n"
    ),
    ("import_dry_run_json", "json"): (
        "{\n"
        '  "dry_run": true,\n'
        '  "total": 2,\n'
        '  "preview": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "exchange": "KRX",\n'
        '      "name": "삼성전자",\n'
        '      "type": ""\n'
        "    },\n"
        "    {\n"
        '      "symbol": "AAPL",\n'
        '      "exchange": "NASDAQ",\n'
        '      "name": "",\n'
        '      "type": "stock"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("import_dry_run_many", "text"): (
        "  미리보기 (11건 중 상위 10건):\n"
        "      symbol |     exchange |         name |         type\n"
        "---------------------------------------------------------\n"
        "      000001 |          KRX |          종목1 |        stock\n"
        "      000002 |          KRX |          종목2 |        stock\n"
        "      000003 |          KRX |          종목3 |        stock\n"
        "      000004 |          KRX |          종목4 |        stock\n"
        "      000005 |          KRX |          종목5 |        stock\n"
        "      000006 |          KRX |          종목6 |        stock\n"
        "      000007 |          KRX |          종목7 |        stock\n"
        "      000008 |          KRX |          종목8 |        stock\n"
        "      000009 |          KRX |          종목9 |        stock\n"
        "      000010 |          KRX |         종목10 |        stock\n"
    ),
    ("import_dry_run_many", "json"): (
        "{\n"
        '  "dry_run": true,\n'
        '  "total": 11,\n'
        '  "preview": [\n'
        "    {\n"
        '      "symbol": "000001",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목1",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000002",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목2",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000003",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목3",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000004",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목4",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000005",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목5",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000006",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목6",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000007",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목7",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000008",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목8",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000009",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목9",\n'
        '      "type": "stock"\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000010",\n'
        '      "exchange": "KRX",\n'
        '      "name": "종목10",\n'
        '      "type": "stock"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
}


class TestInstrumentOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_INSTRUMENT_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_INSTRUMENT_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _INSTRUMENT_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _INSTRUMENT_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""


@pytest.mark.parametrize("mode", ["text", "json"])
def test_sync_never_prints_broker_credentials(mode: str) -> None:
    """``sync``는 설정의 브로커 키·계좌번호를 어느 스트림에도 내지 않는다."""
    result, _ = _invoke_case("sync", mode, mix_stderr=False)
    assert result.exit_code == 0, result.output
    for value in _BROKER_CONFIG.values():
        assert value not in result.stdout
        assert value not in result.stderr


@pytest.mark.parametrize("mode", ["text", "json"])
def test_import_path_appears_only_in_json_stdout(tmp_path: Path, mode: str) -> None:
    """``import``가 받은 파일 경로(사용자 이름이 들 수 있다)는 JSON의 stdout에
    한 번 나가고 text에는 나가지 않으며 stderr에는 나가지 않는다."""
    marker = "user-name-marker"
    target = tmp_path / marker / "inst.csv"
    target.parent.mkdir()
    target.write_text(_CSV_HEADER + "".join(_CSV_ROWS), encoding="utf-8")
    args = ["instrument", "import", str(target)]
    result, _ = _invoke_case("import_csv", mode, mix_stderr=False, args=args)
    assert result.exit_code == 0, result.output
    assert result.stdout.count(marker) == (1 if mode == "json" else 0)
    assert marker not in result.stderr
