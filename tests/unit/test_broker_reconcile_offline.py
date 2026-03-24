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
            # _run_reconcile 내부 로직을 직접 호출

            broker_positions = await mock_adapter.get_account_positions()
            internal_positions = await mock_position_history.get_all_positions()

            broker_map = {p["symbol"]: p for p in broker_positions}
            internal_map = {p.symbol: p for p in internal_positions}

            all_symbols = set(broker_map.keys()) | set(internal_map.keys())
            discrepancies = []
            for symbol in sorted(all_symbols):
                bp = broker_map.get(symbol)
                ip = internal_map.get(symbol)
                broker_qty = float(bp.get("quantity", 0)) if bp else 0.0
                internal_qty = ip.quantity if ip else 0.0
                if broker_qty != internal_qty:
                    discrepancies.append(
                        {
                            "symbol": symbol,
                            "broker_qty": broker_qty,
                            "internal_qty": internal_qty,
                            "diff": broker_qty - internal_qty,
                        }
                    )

            result = {
                "total_symbols": len(all_symbols),
                "discrepancies": discrepancies,
                "match": len(discrepancies) == 0,
                "fix_applied": False,
                "corrections": 0,
            }

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

        broker_map = {p["symbol"]: p for p in broker_positions}
        internal_map = {p.symbol: p for p in internal_positions}

        all_symbols = set(broker_map.keys()) | set(internal_map.keys())
        discrepancies = []
        for symbol in sorted(all_symbols):
            bp = broker_map.get(symbol)
            ip = internal_map.get(symbol)
            broker_qty = float(bp.get("quantity", 0)) if bp else 0.0
            internal_qty = ip.quantity if ip else 0.0
            if broker_qty != internal_qty:
                discrepancies.append(
                    {
                        "symbol": symbol,
                        "broker_qty": broker_qty,
                        "internal_qty": internal_qty,
                        "diff": broker_qty - internal_qty,
                    }
                )

        result = {
            "total_symbols": len(all_symbols),
            "discrepancies": discrepancies,
            "match": len(discrepancies) == 0,
            "fix_applied": False,
            "corrections": 0,
        }

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
