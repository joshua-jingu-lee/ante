"""``treasury snapshot``·``portfolio history``의 날짜 기본값 (#2584).

날짜 옵션이 없으면 가장 최근 스냅샷을 돌려주고, 기본 종료일·시작일은 스냅샷
키(KST 날짜)와 같은 기준으로 잡는다. 실제 ``Treasury``와 DB 위에서 시각을
고정해 부른다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.core import Database
from ante.eventbus import EventBus
from ante.member.models import Member, MemberRole, MemberType
from ante.treasury import Treasury

_ACCOUNT = "domestic"
_KST_1120_1200 = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
_KST_1120_0800 = datetime(2026, 11, 19, 23, 0, tzinfo=UTC)

_MASTER = Member(
    member_id="snapshot-kst-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Snapshot KST Master",
    status="active",
    scopes=[],
)


def _set_master(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["member"] = _MASTER


def _total_asset(snapshot_date: str) -> float:
    return 10_000_000.0 + int(snapshot_date[-2:])


@pytest.fixture
def stored(tmp_path: Path) -> Iterator[list[str]]:
    """``_create_treasury``를 실제 ``Treasury``로 바꾸고 저장할 날짜 목록을 준다."""
    dates: list[str] = []

    @asynccontextmanager
    async def _create(
        account_id: str | None = None, *, ctx: click.Context | None = None
    ) -> AsyncIterator[tuple[Treasury, Database]]:
        db = Database(str(tmp_path / "treasury.db"))
        await db.connect()
        try:
            t = Treasury(db=db, eventbus=EventBus(), account_id=_ACCOUNT)
            await t.initialize()
            for d in dates:
                await db.execute(
                    """INSERT INTO treasury_daily_snapshots
                       (account_id, snapshot_date, total_asset, ante_eval_amount,
                        ante_purchase_amount, unallocated, account_balance,
                        total_allocated, bot_count, daily_pnl, daily_return,
                        net_trade_amount, unrealized_pnl)
                       VALUES (?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)""",
                    (_ACCOUNT, d, _total_asset(d)),
                )
            yield t, db
        finally:
            await db.close()

    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_master),
        patch("ante.cli.commands.treasury._create_treasury", new=_create),
    ):
        yield dates


def _invoke(mode: str, *args: str) -> Result:
    runner = CliRunner(mix_stderr=False)
    return runner.invoke(cli, ["--format", mode, "treasury", *args])


def _json_data(result: Result) -> Any:
    assert result.exit_code == 0, (result.stdout, result.stderr)
    return json.loads(result.stdout)["data"]


@pytest.mark.parametrize("manual_clock", [_KST_1120_1200], indirect=True)
def test_default_returns_latest_before_todays_snapshot(
    manual_clock: Any, stored: list[str]
) -> None:
    stored.append("2026-11-19")
    data = _json_data(_invoke("json", "snapshot", "--account", _ACCOUNT))
    assert data["snapshot_date"] == "2026-11-19"
    assert data["total_asset"] == _total_asset("2026-11-19")


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_default_returns_kst_today_snapshot_before_utc_midnight(
    manual_clock: Any, stored: list[str]
) -> None:
    stored.extend(["2026-11-19", "2026-11-20"])
    data = _json_data(_invoke("json", "snapshot", "--account", _ACCOUNT))
    assert data["snapshot_date"] == "2026-11-20"
    assert data["total_asset"] == _total_asset("2026-11-20")


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_default_without_any_snapshot_json(
    manual_clock: Any, stored: list[str]
) -> None:
    result = _invoke("json", "snapshot", "--account", _ACCOUNT)
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {
        "status": "error",
        "code": "SNAPSHOT_NOT_FOUND",
        "message": "저장된 스냅샷이 없습니다.",
    }
    assert result.stderr == ""


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_default_without_any_snapshot_text(
    manual_clock: Any, stored: list[str]
) -> None:
    result = _invoke("text", "snapshot", "--account", _ACCOUNT)
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "Error: SNAPSHOT_NOT_FOUND: 저장된 스냅샷이 없습니다."
    ]


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_from_only_ends_at_kst_today(manual_clock: Any, stored: list[str]) -> None:
    stored.extend(["2026-11-19", "2026-11-20"])
    data = _json_data(
        _invoke("json", "snapshot", "--account", _ACCOUNT, "--from", "2026-11-01")
    )
    assert [s["snapshot_date"] for s in data["snapshots"]] == [
        "2026-11-19",
        "2026-11-20",
    ]


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_portfolio_history_default_window_is_kst(
    manual_clock: Any, stored: list[str]
) -> None:
    stored.extend(["2026-10-20", "2026-10-21", "2026-11-20"])
    data = _json_data(_invoke("json", "portfolio", "history", "--account", _ACCOUNT))
    assert data["end_date"] == "2026-11-20"
    assert data["start_date"] == "2026-10-21"
    assert [row["date"] for row in data["data"]] == ["2026-10-21", "2026-11-20"]


@pytest.mark.parametrize("manual_clock", [_KST_1120_0800], indirect=True)
def test_explicit_date_is_queried_as_given(
    manual_clock: Any, stored: list[str]
) -> None:
    stored.extend(["2026-11-19", "2026-11-20"])
    data = _json_data(
        _invoke("json", "snapshot", "--account", _ACCOUNT, "--date", "2026-11-19")
    )
    assert data["snapshot_date"] == "2026-11-19"
