"""가상 계좌의 수동 대사 거부 (#2818).

D-ACC-09 매트릭스에서 reconcile 이 면제인 계좌(가상)는 수동 대사를 브로커 조회
전에 ``ACCOUNT_RECONCILE_NOT_APPLICABLE``로 거부한다. 계좌 서비스의 판정, 오류
레지스트리, 서버가 꺼졌을 때의 CLI 경로를 실제 ``AccountService``와 임시 DB 위에서
잠근다. 실전 계좌는 판정을 통과해 브로커 조회(대역 어댑터)까지 닿는다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.account.errors import (
    AccountNotFoundError,
    AccountReconcileNotApplicableError,
)
from ante.account.models import Account, TradingMode
from ante.account.presets import BROKER_PRESETS
from ante.account.service import AccountService
from ante.cli.main import cli
from ante.contracts.helpers import error_spec_for_exception
from ante.contracts.ipc_client_errors import IPCServerNotRunningError
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.member.models import Member, MemberRole, MemberType

_CODE = "ACCOUNT_RECONCILE_NOT_APPLICABLE"
_CREDENTIALS = {"app_key": "k", "app_secret": "s", "account_no": "12345678-01"}


def _account(account_id: str, broker_type: str, mode: str) -> Account:
    preset = BROKER_PRESETS[broker_type]
    return Account(
        account_id=account_id,
        name=account_id,
        exchange=preset.exchange,
        currency=preset.currency,
        broker_type=broker_type,
        trading_mode=TradingMode(mode),
        credentials=dict(_CREDENTIALS),
    )


_MATRIX = [
    pytest.param("test", "virtual", True, id="test-virtual"),
    pytest.param("mock", "virtual", True, id="mock-virtual"),
    pytest.param("kis-domestic", "virtual", True, id="kis-virtual"),
    pytest.param("kis-domestic", "live", False, id="kis-live"),
]


async def _seed(db_path: Path, accounts: list[Account]) -> None:
    db = Database(str(db_path))
    await db.connect()
    try:
        service = AccountService(db=db, eventbus=EventBus())
        await service.initialize()
        for account in accounts:
            await service.create(account)
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("broker_type", "mode", "rejected"), _MATRIX)
async def test_ensure_reconcile_applicable_follows_the_matrix(
    tmp_path: Path, broker_type: str, mode: str, rejected: bool
) -> None:
    db = Database(str(tmp_path / "ante.db"))
    await db.connect()
    try:
        service = AccountService(db=db, eventbus=EventBus())
        await service.initialize()
        await service.create(_account("acc-1", broker_type, mode))
        with patch.object(
            AccountService, "_build_broker_adapter", new=AsyncMock()
        ) as build:
            if rejected:
                with pytest.raises(AccountReconcileNotApplicableError) as info:
                    await service.ensure_reconcile_applicable("acc-1")
                assert info.value.code == _CODE
            else:
                assert await service.ensure_reconcile_applicable("acc-1") is None
        build.assert_not_awaited()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ensure_reconcile_applicable_on_a_missing_account(
    tmp_path: Path,
) -> None:
    db = Database(str(tmp_path / "ante.db"))
    await db.connect()
    try:
        service = AccountService(db=db, eventbus=EventBus())
        await service.initialize()
        with pytest.raises(AccountNotFoundError):
            await service.ensure_reconcile_applicable("nope-1")
    finally:
        await db.close()


def test_the_error_maps_to_a_state_conflict() -> None:
    spec = error_spec_for_exception(AccountReconcileNotApplicableError("x"))
    assert (spec.code, spec.category) == (_CODE, "state_conflict")


def _set_master(ctx: Any) -> None:
    ctx.obj.update(
        {
            "member": Member(
                member_id="m",
                type=MemberType.HUMAN,
                role=MemberRole.MASTER,
                org="default",
                name="m",
                status="active",
                scopes=[],
            )
        }
    )


def _offline_reconcile(
    tmp_path: Path, account: Account
) -> tuple[Any, AsyncMock, AsyncMock]:
    db_path = tmp_path / "db" / "ante.db"
    db_path.parent.mkdir()
    asyncio.run(_seed(db_path, [account]))

    adapter = AsyncMock()
    adapter.get_account_positions = AsyncMock(
        return_value=[{"symbol": "005930", "quantity": "10"}]
    )
    adapter.disconnect = AsyncMock()
    build = AsyncMock(return_value=adapter)
    ipc = AsyncMock(side_effect=IPCServerNotRunningError("server down"))
    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_master),
        patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc),
        patch.object(AccountService, "_build_broker_adapter", new=build),
    ):
        result = CliRunner(mix_stderr=False).invoke(
            cli,
            [
                "--config-dir",
                str(tmp_path),
                "--format",
                "json",
                "broker",
                "reconcile",
                "--account",
                account.account_id,
            ],
        )
    ipc.assert_awaited_once()
    return result, build, adapter


@pytest.mark.parametrize("broker_type", ["test", "mock", "kis-domestic"])
def test_offline_reconcile_of_a_virtual_account_is_rejected(
    tmp_path: Path, broker_type: str
) -> None:
    result, build, adapter = _offline_reconcile(
        tmp_path, _account("acc-1", broker_type, "virtual")
    )
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {
        "status": "error",
        "code": _CODE,
        "message": "계좌 'acc-1'는 가상 계좌라 브로커와 대사하지 않습니다. "
        "가상 계좌의 포지션은 내부 기록이 기준입니다.",
    }
    build.assert_not_awaited()
    adapter.connect.assert_not_awaited()
    adapter.get_account_positions.assert_not_awaited()


def test_offline_reconcile_of_a_live_account_reaches_the_broker(
    tmp_path: Path,
) -> None:
    result, build, adapter = _offline_reconcile(
        tmp_path, _account("acc-1", "kis-domestic", "live")
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)["data"]
    assert payload["discrepancies"] == [
        {"symbol": "005930", "broker_qty": 10.0, "internal_qty": 0.0, "diff": 10.0}
    ]
    build.assert_awaited_once_with("acc-1")
    adapter.get_account_positions.assert_awaited_once()
