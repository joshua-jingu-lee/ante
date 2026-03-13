"""리포트 초안 자동 생성 — 백테스트 완료 시 draft 리포트 생성."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ante.report.models import ReportStatus, StrategyReport

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.report.store import ReportStore

logger = logging.getLogger(__name__)


class ReportDraftGenerator:
    """백테스트 결과로부터 리포트 초안을 생성."""

    def __init__(self, report_store: ReportStore, eventbus: EventBus) -> None:
        self._store = report_store
        self._eventbus = eventbus

    async def initialize(self) -> None:
        """EventBus에 핸들러 등록."""
        from ante.eventbus.events import BacktestCompleteEvent

        self._eventbus.subscribe(BacktestCompleteEvent, self._on_backtest_complete)
        logger.info("ReportDraftGenerator 초기화 완료")

    async def _on_backtest_complete(self, event: object) -> None:
        """백테스트 완료 이벤트 핸들러."""
        from ante.eventbus.events import BacktestCompleteEvent

        if not isinstance(event, BacktestCompleteEvent):
            return

        if event.status != "completed":
            logger.debug("백테스트 실패/취소, 초안 생성 스킵: %s", event.backtest_id)
            return

        try:
            result_data = self._load_result(event.result_path)
            if not result_data:
                logger.warning("백테스트 결과 로드 실패: %s", event.result_path)
                return

            report = self.generate_draft(result_data, event.strategy_id)
            await self._store.submit(report)

            from ante.eventbus.events import NotificationEvent

            await self._eventbus.publish(
                NotificationEvent(
                    level="info",
                    message=f"백테스트 리포트 초안 생성: {report.report_id}",
                    detail=(
                        f"전략: {report.strategy_name}, "
                        f"수익률: {report.total_return_pct}%"
                    ),
                    metadata={"report_id": report.report_id},
                )
            )
            logger.info("리포트 초안 생성 완료: %s", report.report_id)
        except Exception:
            logger.exception("리포트 초안 생성 실패: %s", event.backtest_id)

    @staticmethod
    def _load_result(result_path: str) -> dict | None:
        """결과 파일 로드."""
        if not result_path:
            return None
        try:
            from pathlib import Path

            path = Path(result_path)
            if not path.exists():
                return None
            return json.loads(path.read_text())
        except Exception:
            logger.exception("결과 파일 읽기 실패: %s", result_path)
            return None

    @staticmethod
    def generate_draft(
        result_data: dict,
        strategy_id: str = "",
    ) -> StrategyReport:
        """백테스트 결과 딕셔너리로부터 리포트 초안 생성."""
        metrics = result_data.get("metrics", {})
        strategy = result_data.get("strategy", strategy_id or "unknown")

        # 전략 이름/버전 파싱 (format: "name_v1.0.0")
        if "_v" in strategy:
            name, version = strategy.rsplit("_v", 1)
        else:
            name = strategy
            version = "0.0.0"

        period = result_data.get("period", "")
        total_return = result_data.get("total_return_pct", 0.0)
        total_trades = result_data.get("total_trades", 0)
        sharpe = metrics.get("sharpe_ratio")
        mdd = metrics.get("max_drawdown")
        win_rate = metrics.get("win_rate")

        summary = (
            f"백테스트 자동 생성 초안. "
            f"기간: {period}, "
            f"수익률: {total_return}%, "
            f"거래: {total_trades}건"
        )

        return StrategyReport(
            report_id=str(uuid.uuid4()),
            strategy_name=name,
            strategy_version=version,
            strategy_path="",
            status=ReportStatus.DRAFT,
            submitted_at=datetime.now(tz=UTC),
            submitted_by="system",
            backtest_period=period,
            total_return_pct=total_return,
            total_trades=total_trades,
            sharpe_ratio=sharpe,
            max_drawdown_pct=mdd,
            win_rate=win_rate,
            summary=summary,
            detail_json=json.dumps(result_data, default=str),
        )
