"""StrategyContextFactory -- 계좌 거래모드별 StrategyContext 자동 조립."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.account.models import TradingMode
from ante.bot.config import BotConfig
from ante.bot.providers.live import LivePortfolioView
from ante.bot.providers.virtual import (
    VirtualExecutor,
    VirtualOrderView,
    VirtualPortfolioView,
)
from ante.strategy.base import OrderView
from ante.strategy.context import StrategyContext

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.bot.providers.live import (
        LiveOrderView,
        LiveTradeHistoryView,
    )
    from ante.data.store import ParquetStore
    from ante.gateway.gateway import APIGateway
    from ante.strategy.base import DataProvider, TradeHistoryView
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.treasury.manager import TreasuryManager

logger = logging.getLogger(__name__)


class StrategyContextFactory:
    """Account.trading_mode에 따라 적절한 StrategyContext를 생성.

    main.py에서 생성되어 BotManager에 주입된다.

    live mode 에서는 봇별로 ``LiveDataProvider`` 인스턴스를 새로 생성해
    ``account_id`` 를 closure 방식으로 격리한다. strategy 인터페이스
    (``StrategyContext.get_ohlcv``) 는 변경되지 않는다. ``api_gateway`` /
    ``parquet_store`` 가 모두 주입되어 있을 때만 봇별 인스턴스를 만들고,
    미주입이면 fallback ``data_provider`` 를 사용한다 (virtual-only 환경
    호환).
    """

    def __init__(
        self,
        data_provider: DataProvider,
        account_service: AccountService | None = None,
        live_portfolio: LivePortfolioView | None = None,
        live_order_view: LiveOrderView | None = None,
        virtual_executor: VirtualExecutor | None = None,
        live_trade_history: LiveTradeHistoryView | None = None,
        treasury_manager: TreasuryManager | None = None,
        position_history: PositionHistory | None = None,
        api_gateway: APIGateway | None = None,
        parquet_store: ParquetStore | None = None,
        order_tracker: OrderTracker | None = None,
        trade_recorder: TradeRecorder | None = None,
    ) -> None:
        self._data_provider = data_provider
        self._account_service = account_service
        self._live_portfolio = live_portfolio
        self._live_order_view = live_order_view
        self._virtual_executor = virtual_executor
        self._live_trade_history = live_trade_history
        self._treasury_manager = treasury_manager
        self._position_history = position_history
        self._api_gateway = api_gateway
        self._parquet_store = parquet_store
        # #1948: 주입되면 봇별 LiveOrderView 를 account_id closure 로 생성해
        # OrderTracker sync 캐시에서 미체결을 조회한다. 미주입(virtual-only/legacy)
        # 이면 공유 fallback ``live_order_view`` (없으면 빈 결과 stub)를 쓴다.
        self._order_tracker = order_tracker
        # #2139: 주입되면 봇별 LiveTradeHistoryView 를 account_id closure 로 생성해
        # TradeRecorder 조회를 봇 계좌 스코프로 좁힌다(LiveOrderView 패턴 미러).
        # 미주입(virtual-only/legacy/test)이면 공유 fallback
        # ``live_trade_history`` 를 그대로 쓴다.
        self._trade_recorder = trade_recorder

    def create(self, config: BotConfig) -> StrategyContext:
        """BotConfig 기반으로 적절한 StrategyContext 생성.

        AccountService가 주입된 경우 Account.trading_mode로 분기하고,
        없으면 기본값(VIRTUAL)으로 동작한다.
        """
        trading_mode = self._resolve_trading_mode(config)
        if trading_mode == TradingMode.VIRTUAL:
            return self._create_virtual_context(config)
        return self._create_live_context(config)

    def _resolve_trading_mode(self, config: BotConfig) -> TradingMode:
        """계좌의 trading_mode를 조회한다. AccountService 미설정 시 VIRTUAL."""
        if self._account_service is None:
            return TradingMode.VIRTUAL
        account = self._account_service.get_sync(config.account_id)
        if account is None:
            logger.warning("계좌 '%s' 미발견 -- VIRTUAL 모드로 대체", config.account_id)
            return TradingMode.VIRTUAL
        return account.trading_mode

    def _get_live_portfolio(self, config: BotConfig) -> LivePortfolioView:
        """봇의 계좌에 맞는 LivePortfolioView를 반환.

        TreasuryManager가 있으면 계좌별 Treasury로 새 LivePortfolioView를 생성하고,
        없으면 기본 live_portfolio를 반환한다.
        """
        if self._treasury_manager and self._position_history:
            try:
                treasury = self._treasury_manager.get(config.account_id)
                return LivePortfolioView(
                    treasury=treasury,
                    position_history=self._position_history,
                    account_id=config.account_id,
                )
            except KeyError:
                logger.warning(
                    "계좌 '%s'의 Treasury 미발견 -- 기본 포트폴리오 사용",
                    config.account_id,
                )

        if self._live_portfolio is not None:
            return self._live_portfolio

        msg = "Live 봇 생성에 필요한 Portfolio Provider가 설정되지 않았습니다"
        raise ValueError(msg)

    def _resolve_live_order_view(self, config: BotConfig) -> OrderView:
        """봇별 LiveOrderView 를 결정 (#1948).

        ``order_tracker`` 가 주입돼 있으면 ``config.account_id`` 를 closure 로
        binding 한 **봇별** ``LiveOrderView`` 를 생성한다(``LiveDataProvider`` 패턴
        미러). 단일계좌 다중봇에서 봇별 account scope 격리를 보장한다. 미주입이면
        공유 fallback ``live_order_view`` 를, 그것도 없으면 빈 결과 stub 을 쓴다
        (virtual-only/legacy 환경 호환 — 회귀 방지).
        """
        if self._order_tracker is not None:
            from ante.bot.providers.live import LiveOrderView

            return LiveOrderView(
                order_tracker=self._order_tracker,
                account_id=config.account_id,
            )
        if self._live_order_view is not None:
            return self._live_order_view
        return _EmptyOrderView()

    def _resolve_live_trade_history(self, config: BotConfig) -> TradeHistoryView | None:
        """봇별 LiveTradeHistoryView 를 결정 (#2139).

        ``trade_recorder`` 가 주입돼 있으면 ``config.account_id`` 를 closure 로
        binding 한 **봇별** ``LiveTradeHistoryView`` 를 생성한다(``LiveOrderView``
        #1948 패턴 미러). 단일계좌 다중봇에서 봇 계좌 scope 격리를 보장해 타 계좌
        거래 이력이 전략 컨텍스트에 누출되지 않게 한다. 미주입이면 공유 fallback
        ``live_trade_history`` 를 그대로 반환한다(virtual-only/legacy/test 환경
        호환 — 공유 인스턴스의 private 멤버에 접근하지 않는다).
        """
        if self._trade_recorder is not None:
            from ante.bot.providers.live import LiveTradeHistoryView

            return LiveTradeHistoryView(
                trade_recorder=self._trade_recorder,
                account_id=config.account_id,
            )
        return self._live_trade_history

    def _create_live_context(self, config: BotConfig) -> StrategyContext:
        """Live 봇용 StrategyContext 생성.

        ``APIGateway`` 가 주입돼 있으면 봇별로 새 ``LiveDataProvider``
        인스턴스를 만들어 ``config.account_id`` 를 closure 로 binding 한다.
        그 외 환경에서는 공유 ``self._data_provider`` 를 그대로 사용한다.

        OrderView 도 동일하게 ``order_tracker`` 주입 시 봇별 ``LiveOrderView`` 를
        생성해 ``account_id`` 를 closure 로 격리한다(#1948).
        """
        portfolio = self._get_live_portfolio(config)
        order_view = self._resolve_live_order_view(config)

        data_provider = self._data_provider
        if self._api_gateway is not None:
            from ante.gateway.data_provider import LiveDataProvider

            data_provider = LiveDataProvider(
                gateway=self._api_gateway,
                parquet_store=self._parquet_store,
                account_id=config.account_id,
            )

        ctx = StrategyContext(
            bot_id=config.bot_id,
            data_provider=data_provider,
            portfolio=portfolio,
            order_view=order_view,
            trade_history=self._resolve_live_trade_history(config),
        )
        logger.info("Live StrategyContext 생성: %s", config.bot_id)
        return ctx

    def _create_virtual_context(self, config: BotConfig) -> StrategyContext:
        """Virtual 계좌 봇용 StrategyContext 생성.

        virtual 계좌 봇이라도 OHLCV / price 조회는 봇의 account_id 로
        APIGateway 를 호출해야 한다 (broker routing). live 와 동일하게
        ``api_gateway`` 가 있으면 봇별 LiveDataProvider 를 생성한다.
        """
        initial_balance = self._resolve_virtual_balance(config)
        virtual_portfolio = VirtualPortfolioView(
            bot_id=config.bot_id,
            initial_balance=initial_balance,
        )
        virtual_order_view = VirtualOrderView(portfolio=virtual_portfolio)

        # VirtualExecutor에 봇 등록
        if self._virtual_executor:
            self._virtual_executor.register_bot(config.bot_id, virtual_portfolio)

        data_provider = self._data_provider
        if self._api_gateway is not None:
            from ante.gateway.data_provider import LiveDataProvider

            data_provider = LiveDataProvider(
                gateway=self._api_gateway,
                parquet_store=self._parquet_store,
                account_id=config.account_id,
            )

        ctx = StrategyContext(
            bot_id=config.bot_id,
            data_provider=data_provider,
            portfolio=virtual_portfolio,
            order_view=virtual_order_view,
        )
        logger.info(
            "Virtual StrategyContext 생성: %s (잔고: %s)",
            config.bot_id,
            initial_balance,
        )
        return ctx

    def _resolve_virtual_balance(self, config: BotConfig) -> float:
        """Virtual 계좌 봇의 초기 잔고를 Account 레벨(Treasury)에서 조회.

        Treasury에 해당 봇의 예산이 배정되어 있으면 allocated 값을 사용하고,
        Treasury가 없으면 0.0을 반환한다.
        """
        if self._treasury_manager is not None:
            try:
                treasury = self._treasury_manager.get(config.account_id)
                budget = treasury.get_budget(config.bot_id)
                if budget is not None:
                    return budget.allocated
            except KeyError:
                logger.warning(
                    "Virtual 계좌 봇 '%s': 계좌 '%s'의 Treasury 미발견 -- 잔고 0",
                    config.bot_id,
                    config.account_id,
                )
        return 0.0


class _EmptyOrderView(OrderView):
    """order_tracker 와 공유 live_order_view 가 모두 미주입일 때의 fallback.

    virtual-only/legacy 환경에서 LIVE 컨텍스트 생성이 ValueError 로 깨지지 않도록
    빈 미체결 목록을 반환한다(#1948 회귀 방지).
    """

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        return []
