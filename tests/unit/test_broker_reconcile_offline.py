"""broker reconcile 오프라인 폴백 테스트.

서버 미실행 시 직접 DB에 접근하는 오프라인 경로가
불필요한 의존성(PerformanceTracker, TradeRecorder, TradeService) 없이
PositionHistory만으로 동작하는지 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BROKER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ante"
    / "cli"
    / "commands"
    / "broker.py"
).read_text()


@dataclass(frozen=True)
class _FakePosition:
    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0
    updated_at: str = ""
    exchange: str = "KRX"
    account_id: str = "default"


def _make_click_context(*, fix: bool = False) -> MagicMock:
    """Click Context mock을 생성한다."""
    ctx = MagicMock()
    ctx.obj = {"format": "json"}
    ctx.params = {}
    return ctx


def _offline_reconcile_result(broker_positions, internal_positions) -> dict:
    """``broker.py`` 오프라인 폴백 합산 로직 1:1 미러 (#2120).

    src ``_run_reconcile`` 와 동일하게 broker/internal 을 **심볼별 합산**한 뒤
    비교한다. 같은 심볼을 가진 다중봇 internal 을 덮어쓰지 않고 합산해야
    per-bot false discrepancy 가 사라진다.
    """
    broker_totals: dict[str, float] = {}
    for bp in broker_positions:
        b_qty = float(bp.get("quantity", 0) or 0)
        if b_qty != 0:
            sym = bp["symbol"]
            broker_totals[sym] = broker_totals.get(sym, 0.0) + b_qty
    internal_totals: dict[str, float] = {}
    for ip in internal_positions:
        internal_totals[ip.symbol] = internal_totals.get(ip.symbol, 0.0) + ip.quantity

    all_symbols = set(broker_totals.keys()) | set(internal_totals.keys())
    discrepancies = []
    for symbol in sorted(all_symbols):
        broker_qty = broker_totals.get(symbol, 0.0)
        internal_qty = internal_totals.get(symbol, 0.0)
        if broker_qty != internal_qty:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "broker_qty": broker_qty,
                    "internal_qty": internal_qty,
                    "diff": broker_qty - internal_qty,
                }
            )
    return {
        "total_symbols": len(all_symbols),
        "discrepancies": discrepancies,
        "match": len(discrepancies) == 0,
        "fix_applied": False,
        "corrections": 0,
    }


class TestReconcileOfflineNoDeps:
    """오프라인 폴백 경로에서 불필요한 의존성이 제거되었는지 확인한다."""

    def test_no_performance_tracker_import(self) -> None:
        """오프라인 폴백 코드에 PerformanceTracker 관련 코드가 없어야 한다."""
        assert "PerformanceTracker" not in _BROKER_SOURCE

    def test_no_trade_service_import(self) -> None:
        """오프라인 폴백 코드에 TradeService 관련 코드가 없어야 한다."""
        assert "TradeService" not in _BROKER_SOURCE

    def test_no_trade_recorder_import(self) -> None:
        """오프라인 폴백 코드에 TradeRecorder 관련 코드가 없어야 한다."""
        assert "TradeRecorder" not in _BROKER_SOURCE


class TestReconcileOfflineLogic:
    """오프라인 폴백 경로의 대사 로직을 검증한다."""

    @pytest.fixture()
    def mock_adapter(self) -> AsyncMock:
        adapter = AsyncMock()
        adapter.disconnect = AsyncMock()
        return adapter

    @pytest.fixture()
    def mock_db(self) -> AsyncMock:
        db = AsyncMock()
        db.close = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_reconcile_offline_no_discrepancies(
        self, mock_adapter: AsyncMock, mock_db: AsyncMock
    ) -> None:
        """브로커 포지션과 내부 포지션이 일치하면 match=True를 반환해야 한다."""
        # 브로커 포지션
        mock_adapter.get_account_positions = AsyncMock(
            return_value=[
                {"symbol": "005930", "quantity": "10"},
                {"symbol": "000660", "quantity": "5"},
            ]
        )

        # 내부 포지션 (PositionHistory)
        internal = [
            _FakePosition(
                bot_id="bot1", symbol="005930", quantity=10.0, avg_entry_price=70000
            ),
            _FakePosition(
                bot_id="bot2", symbol="000660", quantity=5.0, avg_entry_price=120000
            ),
        ]

        mock_position_history = AsyncMock()
        mock_position_history.initialize = AsyncMock()
        mock_position_history.get_all_positions = AsyncMock(return_value=internal)

        with (
            patch(
                "ante.cli.commands.broker._get_broker",
                return_value=(mock_adapter, mock_db),
            ),
            patch(
                "ante.trade.position.PositionHistory",
                return_value=mock_position_history,
            ),
        ):
            # _run_reconcile 내부 로직(#2120 합산)을 직접 미러 호출

            broker_positions = await mock_adapter.get_account_positions()
            internal_positions = await mock_position_history.get_all_positions()
            result = _offline_reconcile_result(broker_positions, internal_positions)

            assert result["match"] is True
            assert result["total_symbols"] == 2
            assert result["discrepancies"] == []

    @pytest.mark.asyncio
    async def test_reconcile_offline_with_discrepancies(
        self, mock_adapter: AsyncMock, mock_db: AsyncMock
    ) -> None:
        """수량 불일치가 있으면 discrepancies 목록에 포함해야 한다."""
        mock_adapter.get_account_positions = AsyncMock(
            return_value=[
                {"symbol": "005930", "quantity": "10"},
                {"symbol": "035720", "quantity": "20"},
            ]
        )

        internal = [
            _FakePosition(
                bot_id="bot1", symbol="005930", quantity=8.0, avg_entry_price=70000
            ),
        ]

        mock_position_history = AsyncMock()
        mock_position_history.initialize = AsyncMock()
        mock_position_history.get_all_positions = AsyncMock(return_value=internal)

        broker_positions = await mock_adapter.get_account_positions()
        internal_positions = await mock_position_history.get_all_positions()
        result = _offline_reconcile_result(broker_positions, internal_positions)

        assert result["match"] is False
        assert result["total_symbols"] == 2
        assert len(result["discrepancies"]) == 2

        # 005930: broker 10, internal 8 -> diff 2
        d_005930 = next(d for d in result["discrepancies"] if d["symbol"] == "005930")
        assert d_005930["broker_qty"] == 10.0
        assert d_005930["internal_qty"] == 8.0
        assert d_005930["diff"] == 2.0

        # 035720: broker 20, internal 0 -> diff 20
        d_035720 = next(d for d in result["discrepancies"] if d["symbol"] == "035720")
        assert d_035720["broker_qty"] == 20.0
        assert d_035720["internal_qty"] == 0.0
        assert d_035720["diff"] == 20.0

    @pytest.mark.asyncio
    async def test_reconcile_offline_multi_bot_same_symbol_sum(
        self, mock_adapter: AsyncMock, mock_db: AsyncMock
    ) -> None:
        """(#2120) 같은 심볼을 보유한 다중봇 internal 을 합산해 비교한다.

        bot1 30주 + bot2 70주 = 100주, 브로커 100주 → 합산 일치(불일치 없음).
        이전 ``{p.symbol: p}`` 덮어쓰기는 한 봇 수량만 비교해 false discrepancy
        를 만들었다(per-bot 오판). 합산으로 제거됨을 검증한다.
        """
        mock_adapter.get_account_positions = AsyncMock(
            return_value=[{"symbol": "005930", "quantity": "100"}]
        )
        internal = [
            _FakePosition(
                bot_id="bot1", symbol="005930", quantity=30.0, avg_entry_price=70000
            ),
            _FakePosition(
                bot_id="bot2", symbol="005930", quantity=70.0, avg_entry_price=70000
            ),
        ]
        mock_position_history = AsyncMock()
        mock_position_history.initialize = AsyncMock()
        mock_position_history.get_all_positions = AsyncMock(return_value=internal)

        broker_positions = await mock_adapter.get_account_positions()
        internal_positions = await mock_position_history.get_all_positions()
        result = _offline_reconcile_result(broker_positions, internal_positions)

        # 합산 100 == 브로커 100 → 불일치 없음 (false-positive 제거).
        assert result["match"] is True
        assert result["discrepancies"] == []


class TestReconcileOfflineSourceSums:
    """오프라인 폴백 src 가 internal 을 **합산**(덮어쓰기 금지)하는지 lock (#2120)."""

    def test_source_aggregates_internal_totals(self) -> None:
        """src 에 심볼별 합산 누적 코드(``internal_totals``)가 존재한다."""
        assert "internal_totals" in _BROKER_SOURCE
        assert "broker_totals" in _BROKER_SOURCE

    def test_source_does_not_overwrite_internal_by_symbol(self) -> None:
        """src 가 더 이상 ``{p.symbol: p}`` 덮어쓰기 dict 컴프리헨션을 쓰지 않는다."""
        assert "{p.symbol: p for p in internal_positions}" not in _BROKER_SOURCE


def _run_offline_reconcile(
    tmp_path: Path, internal: list[tuple[str, float]], broker_rows: list[dict]
) -> tuple[dict, AsyncMock]:
    """서버 정지 상태에서 ``broker reconcile`` 을 실제 DB 위에 실행한다."""
    import asyncio
    import json

    import click
    from click.testing import CliRunner

    from ante.cli.commands import broker as broker_cmd
    from ante.cli.main import cli
    from ante.core.database import Database
    from ante.member.models import Member, MemberRole, MemberType
    from ante.trade.position import PositionHistory

    db_path = tmp_path / "db" / "ante.db"
    db_path.parent.mkdir()

    async def _seed() -> None:
        db = Database(str(db_path))
        await db.connect()
        try:
            ph = PositionHistory(db)
            await ph.initialize()
            for bot_id, qty in internal:
                await ph.force_update(
                    bot_id, "005930", qty, 70000.0, account_id="acc-1"
                )
        finally:
            await db.close()

    asyncio.run(_seed())

    adapter = AsyncMock()
    adapter.get_account_positions = AsyncMock(return_value=broker_rows)
    adapter.disconnect = AsyncMock()

    async def _fake_get_broker(account_id=None):  # noqa: ANN001, ANN202
        return adapter, None

    exc = click.ClickException("server down")
    exc.ipc_error_code = "IPC_SERVER_NOT_RUNNING"  # type: ignore[attr-defined]
    master = Member(
        member_id="m",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="m",
        status="active",
        scopes=[],
    )
    with (
        patch("ante.cli.main.authenticate_member") as mock_auth,
        patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(side_effect=exc),
        ),
        patch.object(broker_cmd, "_get_broker", new=_fake_get_broker),
    ):
        mock_auth.side_effect = lambda ctx: ctx.obj.update({"member": master})
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
                "acc-1",
            ],
        )
    return json.loads(result.stdout), adapter


class TestReconcileOfflineCliSumsBots:
    """CLI 오프라인 폴백이 계좌 총합 broker 와 전 봇 합산 internal 을 비교한다."""

    def test_two_bots_same_symbol_match_broker_total(self, tmp_path: Path) -> None:
        payload, adapter = _run_offline_reconcile(
            tmp_path,
            [("bot-a", 6.0), ("bot-b", 4.0)],
            [{"symbol": "005930", "quantity": "10"}],
        )
        adapter.get_account_positions.assert_awaited_once()
        assert payload["discrepancies"] == []
        assert payload["match"] is True

    def test_broker_rows_summed_per_symbol(self, tmp_path: Path) -> None:
        payload, adapter = _run_offline_reconcile(
            tmp_path,
            [("bot-a", 10.0)],
            [
                {"symbol": "005930", "quantity": "6"},
                {"symbol": "005930", "quantity": "4"},
            ],
        )
        adapter.get_account_positions.assert_awaited_once()
        assert payload["discrepancies"] == []
        assert payload["match"] is True

    def test_offline_path_is_detect_only(self, tmp_path: Path) -> None:
        payload, _ = _run_offline_reconcile(
            tmp_path,
            [("bot-a", 3.0)],
            [{"symbol": "005930", "quantity": "10"}],
        )
        assert payload["match"] is False
        assert payload["fix_applied"] is False
        assert payload["corrections"] == 0

        import asyncio

        from ante.core.database import Database
        from ante.trade.position import PositionHistory

        async def _positions() -> list[tuple[str, str, float]]:
            db = Database(str(tmp_path / "db" / "ante.db"))
            await db.connect()
            try:
                ph = PositionHistory(db)
                await ph.initialize()
                snapshots = await ph.get_all_positions(account_id="acc-1")
                return sorted((p.bot_id, p.symbol, p.quantity) for p in snapshots)
            finally:
                await db.close()

        assert asyncio.run(_positions()) == [("bot-a", "005930", 3.0)]
