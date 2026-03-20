"""StrategyContextFactory — 계좌 거래모드별 StrategyContext 자동 조립."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.account.models import TradingMode
from ante.bot.config import BotConfig
from ante.bot.providers.paper import PaperExecutor, PaperOrderView, PaperPortfolioView
from ante.strategy.context import StrategyContext

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.bot.providers.live import (
        LiveOrderView,
        LivePortfolioView,
        LiveTradeHistoryView,
    )
    from ante.strategy.base import DataProvider

logger = logging.getLogger(__name__)


class StrategyContextFactory:
    """Account.trading_mode에 따라 적절한 StrategyContext를 생성.

    main.py에서 생성되어 BotManager에 주입된다.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        account_service: AccountService | None = None,
        live_portfolio: LivePortfolioView | None = None,
        live_order_view: LiveOrderView | None = None,
        paper_executor: PaperExecutor | None = None,
        live_trade_history: LiveTradeHistoryView | None = None,
    ) -> None:
        self._data_provider = data_provider
        self._account_service = account_service
        self._live_portfolio = live_portfolio
        self._live_order_view = live_order_view
        self._paper_executor = paper_executor
        self._live_trade_history = live_trade_history

    def create(self, config: BotConfig) -> StrategyContext:
        """BotConfig 기반으로 적절한 StrategyContext 생성.

        AccountService가 주입된 경우 Account.trading_mode로 분기하고,
        없으면 기본값(paper)으로 동작한다.
        """
        trading_mode = self._resolve_trading_mode(config)
        if trading_mode == TradingMode.VIRTUAL:
            return self._create_paper_context(config)
        return self._create_live_context(config)

    def _resolve_trading_mode(self, config: BotConfig) -> TradingMode:
        """계좌의 trading_mode를 조회한다. AccountService 미설정 시 VIRTUAL."""
        if self._account_service is None:
            return TradingMode.VIRTUAL
        account = self._account_service.get_sync(config.account_id)
        if account is None:
            logger.warning("계좌 '%s' 미발견 — VIRTUAL 모드로 대체", config.account_id)
            return TradingMode.VIRTUAL
        return account.trading_mode

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
            trade_history=self._live_trade_history,
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
