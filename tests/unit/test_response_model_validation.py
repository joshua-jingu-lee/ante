"""응답 모델 호환성 검증 테스트.

각 엔드포인트 핸들러가 반환하는 dict 구조가 선언된 response_model과
호환되는지 model_validate()로 검증한다.
"""

from __future__ import annotations

import pytest

from ante.web.schemas import (
    ApprovalDetailResponse,
    ApprovalListResponse,
    ApprovalUpdateResponse,
    AuditLogListResponse,
    BalanceSetResponse,
    BotDetailResponse,
    BotListResponse,
    BudgetListResponse,
    BudgetOperationResponse,
    ConfigListResponse,
    ConfigUpdateResponse,
    DailySummaryResponse,
    DataSchemaResponse,
    DatasetListResponse,
    ErrorResponse,
    FeedStatusResponse,
    HealthResponse,
    KillSwitchResponse,
    LoginResponse,
    LogoutResponse,
    MemberCreateResponse,
    MemberDetailResponse,
    MemberListResponse,
    MemberScopesResponse,
    MemberTokenResponse,
    MeResponse,
    MonthlySummaryResponse,
    OkResponse,
    PortfolioHistoryResponse,
    PortfolioValueResponse,
    ReportDetailResponse,
    ReportListResponse,
    ReportSubmitResponse,
    SeedResetResponse,
    StatusResponse,
    StorageSummaryResponse,
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyPerformanceResponse,
    StrategyTradesResponse,
    StrategyValidateResponse,
    TradeListResponse,
    TransactionListResponse,
    TreasurySummaryResponse,
    WeeklySummaryResponse,
)

# ── 시스템 라우트 응답 모델 ──────────────────────────


class TestSystemResponseModels:
    """system.py 핸들러 반환값과 응답 모델 호환성."""

    def test_status_response_basic(self):
        """GET /api/system/status — 기본 응답 (account_service 없음)."""
        data = {"status": "running", "version": "0.1.0"}
        model = StatusResponse.model_validate(data)
        assert model.status == "running"
        assert model.version == "0.1.0"
        assert model.trading_status is None

    def test_status_response_with_trading_status(self):
        """GET /api/system/status — account_service가 있을 때."""
        data = {
            "status": "running",
            "version": "0.1.0",
            "trading_status": "ACTIVE",
        }
        model = StatusResponse.model_validate(data)
        assert model.trading_status == "ACTIVE"

    def test_status_response_halted(self):
        """GET /api/system/status — HALTED 상태일 때 halt 정보 포함."""
        data = {
            "status": "running",
            "version": "0.1.0",
            "trading_status": "HALTED",
            "halt_time": "2026-03-19T10:00:00Z",
            "halt_reason": "긴급 중단",
        }
        model = StatusResponse.model_validate(data)
        assert model.halt_time == "2026-03-19T10:00:00Z"
        assert model.halt_reason == "긴급 중단"

    def test_health_response(self):
        """GET /api/system/health."""
        data = {"ok": True}
        model = HealthResponse.model_validate(data)
        assert model.ok is True

    def test_kill_switch_response(self):
        """POST /api/system/kill-switch."""
        data = {"status": "halted", "changed_at": "2026-03-19T10:00:00+00:00"}
        model = KillSwitchResponse.model_validate(data)
        assert model.status == "halted"


# ── 인증 라우트 응답 모델 ──────────────────────────


class TestAuthResponseModels:
    """auth.py 핸들러 반환값과 응답 모델 호환성."""

    def test_login_response(self):
        """POST /api/auth/login."""
        data = {"member_id": "admin", "name": "관리자", "type": "human"}
        model = LoginResponse.model_validate(data)
        assert model.member_id == "admin"

    def test_logout_response(self):
        """POST /api/auth/logout."""
        data = {"ok": True}
        model = LogoutResponse.model_validate(data)
        assert model.ok is True

    def test_me_response(self):
        """GET /api/auth/me."""
        data = {
            "member_id": "admin",
            "name": "관리자",
            "type": "human",
            "emoji": "👤",
            "role": "owner",
            "login_at": "2026-03-19T10:00:00Z",
        }
        model = MeResponse.model_validate(data)
        assert model.role == "owner"


# ── 봇 라우트 응답 모델 ──────────────────────────


class TestBotResponseModels:
    """bots.py 핸들러 반환값과 응답 모델 호환성."""

    def test_bot_list_response(self):
        """GET /api/bots."""
        data = {
            "bots": [
                {"bot_id": "bot-1", "status": "running", "strategy_id": "s1"},
                {"bot_id": "bot-2", "status": "stopped", "strategy_id": "s2"},
            ],
            "next_cursor": None,
        }
        model = BotListResponse.model_validate(data)
        assert len(model.bots) == 2
        assert model.next_cursor is None

    def test_bot_list_response_with_cursor(self):
        """GET /api/bots — 다음 페이지가 있을 때."""
        data = {
            "bots": [{"bot_id": "bot-1", "status": "running"}],
            "next_cursor": "bot-1",
        }
        model = BotListResponse.model_validate(data)
        assert model.next_cursor == "bot-1"

    def test_bot_detail_response(self):
        """GET /api/bots/{bot_id} — 기본."""
        data = {"bot": {"bot_id": "bot-1", "status": "running", "strategy_id": "s1"}}
        model = BotDetailResponse.model_validate(data)
        assert model.bot.bot_id == "bot-1"

    def test_bot_detail_response_with_extras(self):
        """GET /api/bots/{bot_id} — strategy, budget, positions 포함."""
        data = {
            "bot": {
                "bot_id": "bot-1",
                "status": "running",
                "strategy_id": "s1",
                "strategy": {
                    "name": "TestStrategy",
                    "version": "1.0",
                    "author": "agent",
                    "description": "테스트 전략",
                },
                "budget": {
                    "allocated": 1000000.0,
                    "spent": 500000.0,
                    "reserved": 0.0,
                    "available": 500000.0,
                },
                "positions": [
                    {
                        "symbol": "005930",
                        "quantity": 10.0,
                        "avg_entry_price": 70000.0,
                        "realized_pnl": 0.0,
                    }
                ],
            }
        }
        model = BotDetailResponse.model_validate(data)
        assert model.bot.strategy["name"] == "TestStrategy"


# ── 전략 라우트 응답 모델 ──────────────────────────


class TestStrategyResponseModels:
    """strategies.py 핸들러 반환값과 응답 모델 호환성."""

    def test_validate_response_valid(self):
        """POST /api/strategies/validate — 유효한 전략."""
        data = {"valid": True, "errors": [], "warnings": []}
        model = StrategyValidateResponse.model_validate(data)
        assert model.valid is True

    def test_validate_response_invalid(self):
        """POST /api/strategies/validate — 무효한 전략."""
        data = {
            "valid": False,
            "errors": ["Strategy 클래스를 찾을 수 없습니다"],
            "warnings": [],
        }
        model = StrategyValidateResponse.model_validate(data)
        assert model.valid is False
        assert len(model.errors) == 1

    def test_strategy_list_response(self):
        """GET /api/strategies."""
        data = {
            "strategies": [
                {
                    "id": "s1",
                    "name": "TestStrategy",
                    "version": "1.0",
                    "status": "registered",
                    "author": "agent",
                    "bot_id": None,
                    "bot_status": None,
                },
                {
                    "id": "s2",
                    "name": "Another",
                    "version": "2.0",
                    "status": "deployed",
                    "author": "agent",
                    "bot_id": "bot-1",
                    "bot_status": "running",
                },
            ]
        }
        model = StrategyListResponse.model_validate(data)
        assert len(model.strategies) == 2
        assert model.strategies[1].bot_id == "bot-1"

    def test_strategy_detail_response(self):
        """GET /api/strategies/{strategy_id}."""
        data = {
            "strategy": {
                "strategy_id": "s1",
                "name": "Test",
                "version": "1.0",
                "status": "registered",
            },
            "bot": None,
        }
        model = StrategyDetailResponse.model_validate(data)
        assert model.strategy.strategy_id == "s1"
        assert model.bot is None

    def test_strategy_detail_response_with_bot(self):
        """GET /api/strategies/{strategy_id} — 봇 연결됨."""
        data = {
            "strategy": {"strategy_id": "s1", "name": "Test", "version": "1.0"},
            "bot": {"bot_id": "bot-1", "status": "running"},
        }
        model = StrategyDetailResponse.model_validate(data)
        assert model.bot is not None

    def test_strategy_performance_response(self):
        """GET /api/strategies/{strategy_id}/performance."""
        data = {
            "total_trades": 50,
            "winning_trades": 30,
            "losing_trades": 20,
            "win_rate": 0.6,
            "total_pnl": 150000.0,
            "avg_pnl": 3000.0,
            "max_drawdown": 0.05,
            "profit_factor": 1.5,
            "sharpe_ratio": 1.2,
            "equity_curve": [
                {"date": "2026-03-01", "value": 1000000.0},
                {"date": "2026-03-15", "value": 1150000.0},
            ],
        }
        model = StrategyPerformanceResponse.model_validate(data)
        assert model.total_trades == 50
        assert len(model.equity_curve) == 2

    def test_strategy_performance_extra_fields(self):
        """StrategyPerformanceResponse는 extra='allow'로 커스텀 지표 수용."""
        data = {
            "total_trades": 10,
            "winning_trades": 7,
            "losing_trades": 3,
            "win_rate": 0.7,
            "total_pnl": 50000.0,
            "avg_pnl": 5000.0,
            "max_drawdown": 0.03,
            "profit_factor": 2.0,
            "sharpe_ratio": 1.5,
            "equity_curve": [],
            "custom_metric_alpha": 0.42,
            "sector_exposure": {"IT": 0.5, "금융": 0.3},
        }
        model = StrategyPerformanceResponse.model_validate(data)
        assert model.model_extra["custom_metric_alpha"] == 0.42
        assert model.model_extra["sector_exposure"]["IT"] == 0.5

    def test_daily_summary_response(self):
        """GET /api/strategies/{strategy_id}/daily-summary."""
        data = {
            "items": [
                {
                    "date": "2026-03-18",
                    "realized_pnl": 10000.0,
                    "trade_count": 3,
                    "win_rate": 0.67,
                },
                {
                    "date": "2026-03-19",
                    "realized_pnl": -5000.0,
                    "trade_count": 2,
                    "win_rate": 0.0,
                },
            ]
        }
        model = DailySummaryResponse.model_validate(data)
        assert len(model.items) == 2

    def test_weekly_summary_response(self):
        """GET /api/strategies/{strategy_id}/weekly-summary."""
        data = {
            "items": [
                {
                    "week_start": "2026-03-16",
                    "week_end": "2026-03-22",
                    "week_label": "2026-W12",
                    "realized_pnl": 25000.0,
                    "trade_count": 8,
                    "win_rate": 0.625,
                }
            ]
        }
        model = WeeklySummaryResponse.model_validate(data)
        assert model.items[0].week_label == "2026-W12"

    def test_monthly_summary_response(self):
        """GET /api/strategies/{strategy_id}/monthly-summary."""
        data = {
            "items": [
                {
                    "year": 2026,
                    "month": 3,
                    "realized_pnl": 100000.0,
                    "trade_count": 25,
                    "win_rate": 0.64,
                }
            ]
        }
        model = MonthlySummaryResponse.model_validate(data)
        assert model.items[0].year == 2026

    def test_strategy_trades_response(self):
        """GET /api/strategies/{strategy_id}/trades."""
        data = {
            "trades": [
                {
                    "trade_id": "t-001",
                    "bot_id": "bot-1",
                    "symbol": "005930",
                    "side": "buy",
                    "quantity": 10.0,
                    "price": 70000.0,
                    "status": "filled",
                    "timestamp": "2026-03-19T10:00:00Z",
                }
            ],
            "next_cursor": None,
        }
        model = StrategyTradesResponse.model_validate(data)
        assert model.trades[0].trade_id == "t-001"


# ── Treasury 라우트 응답 모델 ──────────────────────────


class TestTreasuryResponseModels:
    """treasury.py 핸들러 반환값과 응답 모델 호환성."""

    def test_treasury_summary_response_basic(self):
        """GET /api/treasury — 기본 응답."""
        data = {
            "total_balance": 10000000.0,
            "unallocated": 5000000.0,
            "total_allocated": 5000000.0,
            "total_evaluation": 10500000.0,
            "total_profit_loss": 500000.0,
            "commission_rate": 0.00015,
            "sell_tax_rate": 0.0023,
        }
        model = TreasurySummaryResponse.model_validate(data)
        assert model.total_balance == 10000000.0

    def test_treasury_summary_response_with_broker(self):
        """GET /api/treasury — 브로커 연동 시 추가 필드."""
        data = {
            "total_balance": 10000000.0,
            "unallocated": 5000000.0,
            "total_allocated": 5000000.0,
            "total_evaluation": 10500000.0,
            "total_profit_loss": 500000.0,
            "commission_rate": 0.00015,
            "sell_tax_rate": 0.0023,
            "broker_id": "kis",
            "broker_name": "한국투자증권",
            "broker_short_name": "KIS",
            "exchange": "KRX",
            "account_no": "12345678-01",
            "is_virtual": True,
            "synced_at": "2026-03-19T10:00:00+00:00",
        }
        model = TreasurySummaryResponse.model_validate(data)
        assert model.broker_id == "kis"
        assert model.is_virtual is True

    def test_treasury_summary_extra_fields(self):
        """TreasurySummaryResponse는 extra='allow'로 동적 메타데이터 수용."""
        data = {
            "total_balance": 10000000.0,
            "unallocated": 5000000.0,
            "total_allocated": 5000000.0,
            "total_evaluation": 10500000.0,
            "total_profit_loss": 500000.0,
            "commission_rate": 0.00015,
            "sell_tax_rate": 0.0023,
            "custom_broker_field": "extra_value",
        }
        model = TreasurySummaryResponse.model_validate(data)
        assert model.model_extra["custom_broker_field"] == "extra_value"

    def test_transaction_list_response(self):
        """GET /api/treasury/transactions."""
        data = {
            "items": [
                {
                    "id": 1,
                    "type": "deposit",
                    "bot_id": None,
                    "amount": 1000000.0,
                    "description": "초기 입금",
                    "created_at": "2026-03-01T09:00:00Z",
                },
                {
                    "id": 2,
                    "type": "allocate",
                    "bot_id": "bot-1",
                    "amount": 500000.0,
                    "description": "",
                    "created_at": "2026-03-01T10:00:00Z",
                },
            ],
            "total": 2,
        }
        model = TransactionListResponse.model_validate(data)
        assert model.total == 2
        assert model.items[0].type == "deposit"

    def test_budget_operation_response(self):
        """POST /api/treasury/bots/{bot_id}/allocate (또는 deallocate)."""
        data = {
            "bot_id": "bot-1",
            "allocated": 1000000.0,
            "available": 800000.0,
        }
        model = BudgetOperationResponse.model_validate(data)
        assert model.bot_id == "bot-1"

    def test_budget_list_response(self):
        """GET /api/treasury/budgets."""
        data = {
            "budgets": [
                {
                    "bot_id": "bot-1",
                    "allocated": 1000000.0,
                    "spent": 200000.0,
                    "reserved": 0.0,
                    "available": 800000.0,
                }
            ]
        }
        model = BudgetListResponse.model_validate(data)
        assert len(model.budgets) == 1

    def test_balance_set_response(self):
        """POST /api/treasury/balance."""
        data = {
            "total_balance": 15000000.0,
            "updated_at": "2026-03-19T10:00:00+00:00",
        }
        model = BalanceSetResponse.model_validate(data)
        assert model.total_balance == 15000000.0


# ── 데이터 라우트 응답 모델 ──────────────────────────


class TestDataResponseModels:
    """data.py 핸들러 반환값과 응답 모델 호환성."""

    def test_dataset_list_response_empty(self):
        """GET /api/data/datasets — store 없음."""
        data = {"items": [], "total": 0}
        model = DatasetListResponse.model_validate(data)
        assert model.total == 0

    def test_dataset_list_response_with_items(self):
        """GET /api/data/datasets — 데이터셋이 있을 때."""
        data = {
            "items": [
                {
                    "id": "005930__1d",
                    "symbol": "005930",
                    "timeframe": "1d",
                    "data_type": "ohlcv",
                    "start_date": "2020-01-02",
                    "end_date": "2026-03-18",
                    "row_count": 1500,
                },
                {
                    "id": "005930__fundamental",
                    "symbol": "005930",
                    "timeframe": "",
                    "data_type": "fundamental",
                    "start_date": "2020-01-02",
                    "end_date": "2026-03-18",
                    "row_count": 0,
                },
            ],
            "total": 2,
        }
        model = DatasetListResponse.model_validate(data)
        assert model.total == 2
        assert model.items[0].data_type == "ohlcv"

    def test_data_schema_response_ohlcv(self):
        """GET /api/data/schema — OHLCV 스키마 (동적 키)."""
        data = {
            "timestamp": "<class 'str'>",
            "open": "<class 'float'>",
            "high": "<class 'float'>",
            "low": "<class 'float'>",
            "close": "<class 'float'>",
            "volume": "<class 'int'>",
        }
        model = DataSchemaResponse.model_validate(data)
        # extra="allow"이므로 모든 키가 model_extra에 저장됨
        assert "timestamp" in model.model_extra

    def test_data_schema_response_fundamental(self):
        """GET /api/data/schema?data_type=fundamental — fundamental 스키마."""
        data = {
            "date": "<class 'str'>",
            "per": "<class 'float'>",
            "pbr": "<class 'float'>",
        }
        model = DataSchemaResponse.model_validate(data)
        assert "per" in model.model_extra

    def test_storage_summary_response_empty(self):
        """GET /api/data/storage — store 없음."""
        data = {"total_bytes": 0, "total_mb": 0.0, "by_timeframe": {}}
        model = StorageSummaryResponse.model_validate(data)
        assert model.total_bytes == 0

    def test_storage_summary_response_with_data(self):
        """GET /api/data/storage — 데이터가 있을 때."""
        data = {
            "total_bytes": 52428800,
            "total_mb": 50.0,
            "by_timeframe": {"1d": 30.0, "1h": 20.0},
        }
        model = StorageSummaryResponse.model_validate(data)
        assert model.by_timeframe["1d"] == 30.0

    def test_feed_status_response_not_initialized(self):
        """GET /api/data/feed-status — 미초기화 상태."""
        data = {
            "initialized": False,
            "checkpoints": [],
            "recent_reports": [],
            "api_keys": [],
        }
        model = FeedStatusResponse.model_validate(data)
        assert model.initialized is False

    def test_feed_status_response_initialized(self):
        """GET /api/data/feed-status — 초기화 후."""
        data = {
            "initialized": True,
            "checkpoints": [
                {
                    "source": "data_go_kr",
                    "data_type": "ohlcv",
                    "last_date": "2026-03-17",
                    "updated_at": "2026-03-17T16:00:00Z",
                }
            ],
            "recent_reports": [
                {
                    "mode": "daily",
                    "started_at": "2026-03-17T16:00:12Z",
                    "finished_at": "2026-03-17T16:05:34Z",
                    "duration_seconds": 322,
                }
            ],
            "api_keys": [{"name": "DATA_GO_KR_KEY", "configured": True}],
        }
        model = FeedStatusResponse.model_validate(data)
        assert model.initialized is True
        assert len(model.checkpoints) == 1


# ── 거래 라우트 응답 모델 ──────────────────────────


class TestTradeResponseModels:
    """trades.py 핸들러 반환값과 응답 모델 호환성."""

    def test_trade_list_response(self):
        """GET /api/trades."""
        data = {
            "trades": [
                {
                    "trade_id": "t-001",
                    "bot_id": "bot-1",
                    "symbol": "005930",
                    "side": "buy",
                    "quantity": 10.0,
                    "price": 70000.0,
                    "status": "filled",
                    "created_at": "2026-03-19T10:00:00Z",
                }
            ],
            "next_cursor": None,
        }
        model = TradeListResponse.model_validate(data)
        assert model.trades[0].symbol == "005930"

    def test_trade_list_empty(self):
        """GET /api/trades — 비어있을 때."""
        data = {"trades": [], "next_cursor": None}
        model = TradeListResponse.model_validate(data)
        assert len(model.trades) == 0


# ── 리포트 라우트 응답 모델 ──────────────────────────


class TestReportResponseModels:
    """reports.py 핸들러 반환값과 응답 모델 호환성."""

    def test_report_submit_response(self):
        """POST /api/reports."""
        data = {
            "report_id": "rpt-001",
            "strategy": "TestStrategy",
            "status": "pending",
        }
        model = ReportSubmitResponse.model_validate(data)
        assert model.report_id == "rpt-001"

    def test_report_detail_response(self):
        """GET /api/reports/{report_id}."""
        data = {
            "report_id": "rpt-001",
            "strategy_name": "TestStrategy",
            "strategy_version": "1.0",
            "strategy_path": "/path/to/strategy.py",
            "status": "pending",
            "submitted_at": "2026-03-19T10:00:00Z",
            "submitted_by": "agent-1",
            "backtest_period": "2025-01-01~2026-03-18",
            "total_return_pct": 15.5,
            "total_trades": 50,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": 5.0,
            "win_rate": 0.64,
            "summary": "양호한 성과",
            "rationale": "모멘텀 기반",
            "risks": "시장 급변 시 손실",
            "recommendations": "소규모 시작 권장",
            "equity_curve": [{"date": "2025-01-01", "value": 1000000.0}],
            "metrics": {"cagr": 0.12},
            "initial_balance": 1000000.0,
            "final_balance": 1155000.0,
            "symbols": ["005930", "000660"],
            "user_notes": "",
            "reviewed_at": None,
        }
        model = ReportDetailResponse.model_validate(data)
        assert model.total_return_pct == 15.5

    def test_report_detail_response_minimal(self):
        """GET /api/reports/{report_id} — 최소 필드만."""
        data = {
            "report_id": "rpt-002",
            "strategy_name": "Minimal",
            "strategy_version": "0.1",
            "status": "pending",
            "submitted_at": "2026-03-19T10:00:00Z",
        }
        model = ReportDetailResponse.model_validate(data)
        assert model.equity_curve == []
        assert model.metrics == {}

    def test_report_list_response(self):
        """GET /api/reports."""
        data = {
            "reports": [
                {
                    "report_id": "rpt-001",
                    "strategy": "TestStrategy",
                    "status": "pending",
                    "submitted_at": "2026-03-19T10:00:00Z",
                }
            ],
            "next_cursor": None,
        }
        model = ReportListResponse.model_validate(data)
        assert model.reports[0].strategy == "TestStrategy"


# ── 결재 라우트 응답 모델 ──────────────────────────


class TestApprovalResponseModels:
    """approvals.py 핸들러 반환값과 응답 모델 호환성."""

    def test_approval_list_response(self):
        """GET /api/approvals."""
        data = {
            "approvals": [
                {
                    "id": "apr-001",
                    "type": "strategy_deploy",
                    "status": "pending",
                    "requester": "agent-1",
                    "title": "전략 배포 요청",
                    "reference_id": "rpt-001",
                }
            ],
            "total": 1,
        }
        model = ApprovalListResponse.model_validate(data)
        assert model.total == 1

    def test_approval_detail_response(self):
        """GET /api/approvals/{approval_id}."""
        data = {
            "approval": {
                "id": "apr-001",
                "type": "strategy_deploy",
                "status": "pending",
                "requester": "agent-1",
                "title": "전략 배포 요청",
            },
            "report_detail": None,
        }
        model = ApprovalDetailResponse.model_validate(data)
        assert model.report_detail is None

    def test_approval_detail_response_with_report(self):
        """GET /api/approvals/{approval_id} — report_detail 포함."""
        data = {
            "approval": {
                "id": "apr-001",
                "type": "strategy_deploy",
                "status": "pending",
                "requester": "agent-1",
                "title": "전략 배포 요청",
            },
            "report_detail": {
                "report_id": "rpt-001",
                "strategy_name": "Test",
            },
        }
        model = ApprovalDetailResponse.model_validate(data)
        assert model.report_detail is not None

    def test_approval_update_response(self):
        """PATCH /api/approvals/{approval_id}/status."""
        data = {
            "approval": {
                "id": "apr-001",
                "type": "strategy_deploy",
                "status": "approved",
                "requester": "agent-1",
                "title": "전략 배포 요청",
            }
        }
        model = ApprovalUpdateResponse.model_validate(data)
        assert model.approval.status == "approved"


# ── 설정 라우트 응답 모델 ──────────────────────────


class TestConfigResponseModels:
    """config.py 핸들러 반환값과 응답 모델 호환성."""

    def test_config_list_response(self):
        """GET /api/config."""
        data = {
            "configs": [
                {"key": "risk.max_mdd", "value": 0.1, "category": "risk"},
                {"key": "risk.max_position", "value": 5, "category": "risk"},
            ]
        }
        model = ConfigListResponse.model_validate(data)
        assert len(model.configs) == 2

    def test_config_update_response(self):
        """PUT /api/config/{key}."""
        data = {"key": "risk.max_mdd", "old_value": 0.1, "new_value": 0.15}
        model = ConfigUpdateResponse.model_validate(data)
        assert model.key == "risk.max_mdd"

    def test_config_update_response_none_values(self):
        """PUT /api/config/{key} — old/new 값이 None인 경우."""
        data = {"key": "new.setting", "old_value": None, "new_value": "hello"}
        model = ConfigUpdateResponse.model_validate(data)
        assert model.old_value is None


# ── 포트폴리오 라우트 응답 모델 ──────────────────────────


class TestPortfolioResponseModels:
    """portfolio.py 핸들러 반환값과 응답 모델 호환성."""

    def test_portfolio_value_response(self):
        """GET /api/portfolio/value."""
        data = {
            "total_value": 10500000.0,
            "daily_pnl": 50000.0,
            "daily_return": 0.4784,
            "updated_at": "2026-03-19T10:00:00Z",
        }
        model = PortfolioValueResponse.model_validate(data)
        assert model.total_value == 10500000.0

    def test_portfolio_history_response(self):
        """GET /api/portfolio/history."""
        data = {
            "data": [
                {"date": "2026-03-01", "value": 10000000.0},
                {"date": "2026-03-19", "value": 10500000.0},
            ],
            "period": "1m",
        }
        model = PortfolioHistoryResponse.model_validate(data)
        assert model.period == "1m"
        assert len(model.data) == 2

    def test_portfolio_history_response_empty(self):
        """GET /api/portfolio/history — 봇 없음."""
        data = {"data": [], "period": "1m"}
        model = PortfolioHistoryResponse.model_validate(data)
        assert len(model.data) == 0


# ── 멤버 라우트 응답 모델 ──────────────────────────


class TestMemberResponseModels:
    """members.py 핸들러 반환값과 응답 모델 호환성."""

    def test_member_list_response(self):
        """GET /api/members."""
        data = {
            "members": [
                {
                    "member_id": "admin",
                    "name": "관리자",
                    "type": "human",
                    "role": "owner",
                }
            ],
            "total": 1,
        }
        model = MemberListResponse.model_validate(data)
        assert model.total == 1

    def test_member_detail_response(self):
        """GET /api/members/{member_id}."""
        data = {
            "member": {
                "member_id": "admin",
                "name": "관리자",
                "type": "human",
                "role": "owner",
            }
        }
        model = MemberDetailResponse.model_validate(data)
        assert model.member.member_id == "admin"

    def test_member_create_response(self):
        """POST /api/members."""
        data = {
            "member": {
                "member_id": "agent-1",
                "name": "분석 에이전트",
                "type": "agent",
                "role": "agent",
            },
            "token": "tok_abc123def456",
        }
        model = MemberCreateResponse.model_validate(data)
        assert model.token.startswith("tok_")

    def test_member_token_response(self):
        """POST /api/members/{member_id}/rotate-token."""
        data = {
            "member": {
                "member_id": "agent-1",
                "name": "에이전트",
                "type": "agent",
                "role": "agent",
            },
            "token": "tok_new_token_789",
        }
        model = MemberTokenResponse.model_validate(data)
        assert model.token == "tok_new_token_789"

    def test_ok_response(self):
        """PATCH /api/members/{member_id}/password."""
        data = {"ok": True}
        model = OkResponse.model_validate(data)
        assert model.ok is True

    def test_member_scopes_response(self):
        """PUT /api/members/{member_id}/scopes."""
        data = {
            "member": {
                "member_id": "agent-1",
                "name": "에이전트",
                "type": "agent",
                "role": "agent",
                "scopes": ["trade:read", "trade:write"],
            }
        }
        model = MemberScopesResponse.model_validate(data)
        assert model.member.scopes == ["trade:read", "trade:write"]


# ── 감사 로그 라우트 응답 모델 ──────────────────────────


class TestAuditLogResponseModels:
    """audit.py 핸들러 반환값과 응답 모델 호환성."""

    def test_audit_log_list_response(self):
        """GET /api/audit-logs."""
        data = {
            "logs": [
                {
                    "id": 1,
                    "member_id": "admin",
                    "action": "login",
                    "detail": "로그인 성공",
                    "created_at": "2026-03-19T10:00:00Z",
                }
            ],
            "total": 1,
        }
        model = AuditLogListResponse.model_validate(data)
        assert model.total == 1


# ── 에러 응답 모델 ──────────────────────────


class TestErrorResponseModel:
    """ErrorResponse 모델 호환성."""

    def test_error_response_full(self):
        """RFC 7807 에러 응답 전체 필드."""
        data = {
            "type": "/errors/not-found",
            "title": "Not Found",
            "detail": "리소스를 찾을 수 없습니다",
            "status": 404,
            "instance": "/api/bots/nonexistent",
        }
        model = ErrorResponse.model_validate(data)
        assert model.status == 404

    def test_error_response_defaults(self):
        """ErrorResponse 기본값."""
        model = ErrorResponse.model_validate({})
        assert model.type == "/errors/internal"
        assert model.status == 500


# ── 테스트 시드 응답 모델 ──────────────────────────


class TestSeedResponseModels:
    """test_seed.py 핸들러 반환값과 응답 모델 호환성."""

    def test_seed_reset_response(self):
        """POST /api/test/seed/reset."""
        data = {"ok": True, "scenario": "login-dashboard"}
        model = SeedResetResponse.model_validate(data)
        assert model.ok is True
        assert model.scenario == "login-dashboard"


# ── extra="allow" 모델 동적 필드 수용 테스트 ──────────────────────────


class TestExtraAllowModels:
    """extra='allow' 설정된 모델들이 알 수 없는 필드를 수용하는지 검증."""

    @pytest.mark.parametrize(
        "model_cls,base_data",
        [
            (
                StrategyPerformanceResponse,
                {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "avg_pnl": 0.0,
                    "max_drawdown": 0.0,
                    "profit_factor": 0.0,
                    "sharpe_ratio": 0.0,
                    "equity_curve": [],
                },
            ),
            (
                TreasurySummaryResponse,
                {
                    "total_balance": 0.0,
                    "unallocated": 0.0,
                    "total_allocated": 0.0,
                    "total_evaluation": 0.0,
                    "total_profit_loss": 0.0,
                    "commission_rate": 0.00015,
                    "sell_tax_rate": 0.0023,
                },
            ),
            (DataSchemaResponse, {}),
        ],
        ids=[
            "StrategyPerformanceResponse",
            "TreasurySummaryResponse",
            "DataSchemaResponse",
        ],
    )
    def test_accepts_unknown_fields(self, model_cls, base_data):
        """extra='allow' 모델이 선언되지 않은 필드를 수용해야 한다."""
        extra_data = {**base_data, "unknown_field_1": 42, "unknown_field_2": "hello"}
        model = model_cls.model_validate(extra_data)
        assert model.model_extra["unknown_field_1"] == 42
        assert model.model_extra["unknown_field_2"] == "hello"

    @pytest.mark.parametrize(
        "model_cls,base_data",
        [
            (StatusResponse, {"status": "running"}),
            (HealthResponse, {"ok": True}),
            (BotListResponse, {"bots": []}),
        ],
        ids=["StatusResponse", "HealthResponse", "BotListResponse"],
    )
    def test_ignores_unknown_fields_by_default(self, model_cls, base_data):
        """extra='allow'가 아닌 모델은 알 수 없는 필드를 무시해야 한다."""
        extra_data = {**base_data, "unexpected_field": "should_be_ignored"}
        model = model_cls.model_validate(extra_data)
        # extra="allow"가 아니므로 model_extra에 저장되지 않아야 한다
        assert (
            not getattr(model, "model_extra", None)
            or "unexpected_field" not in model.model_extra
        )
