"""StrategyContextFactory — 봇 유형별 StrategyContext 자동 조립."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.bot.config import BotConfig
from ante.bot.providers.paper import PaperExecutor, PaperOrderView, PaperPortfolioView
from ante.strategy.context import StrategyContext

if TYPE_CHECKING:
    from ante.bot.providers.live import LiveOrderView, LivePortfolioView
    from ante.strategy.base import DataProvider

logger = logging.getLogger(__name__)


class StrategyContextFactory:
    """봇 유형(live/paper)에 따라 적절한 StrategyContext를 생성.

    main.py에서 생성되어 BotManager에 주입된다.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        live_portfolio: LivePortfolioView | None = None,
        live_order_view: LiveOrderView | None = None,
        paper_executor: PaperExecutor | None = None,
    ) -> None:
        self._data_provider = data_provider
        self._live_portfolio = live_portfolio
        self._live_order_view = live_order_view
        self._paper_executor = paper_executor

    def create(self, config: BotConfig) -> StrategyContext:
        """BotConfig 기반으로 적절한 StrategyContext 생성."""
        if config.bot_type == "paper":
            return self._create_paper_context(config)
        return self._create_live_context(config)

    def _create_live_context(self, config: BotConfig) -> StrategyContext:
        """Live 봇용 StrategyContext 생성."""
        if self._live_portfolio is None or self._live_order_view is None:
            msg = "Live 봇 생성에 필요한 Provider가 설정되지 않았습니다"
            raise ValueError(msg)

        ctx = StrategyContext(
            bot_id=config.bot_id,
            data_provider=self._data_provider,
            portfolio=self._live_portfolio,
            order_view=self._live_order_view,
        )
        logger.info("Live StrategyContext 생성: %s", config.bot_id)
        return ctx

    def _create_paper_context(self, config: BotConfig) -> StrategyContext:
        """Paper 봇용 StrategyContext 생성."""
        paper_portfolio = PaperPortfolioView(
            bot_id=config.bot_id,
            initial_balance=config.paper_initial_balance,
        )
        paper_order_view = PaperOrderView(portfolio=paper_portfolio)

        # PaperExecutor에 봇 등록
        if self._paper_executor:
            self._paper_executor.register_bot(config.bot_id, paper_portfolio)

        ctx = StrategyContext(
            bot_id=config.bot_id,
            data_provider=self._data_provider,
            portfolio=paper_portfolio,
            order_view=paper_order_view,
        )
        logger.info(
            "Paper StrategyContext 생성: %s (잔고: %s)",
            config.bot_id,
            config.paper_initial_balance,
        )
        return ctx
