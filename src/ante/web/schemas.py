"""Web API Pydantic 요청/응답 모델."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details 에러 응답."""

    type: str = "/errors/internal"
    title: str = "Internal Server Error"
    detail: str = ""
    status: int = 500
    instance: str = ""


# ── 시스템 ──────────────────────────────────────────────


class StatusResponse(BaseModel):
    """시스템 상태 응답."""

    status: str
    version: str = "0.1.0"
    trading_status: str | None = None
    halt_time: str | None = None
    halt_reason: str | None = None


class HealthResponse(BaseModel):
    """헬스체크 응답."""

    ok: bool


class KillSwitchResponse(BaseModel):
    """킬 스위치 제어 응답."""

    status: str
    changed_at: str


# ── 인증 ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    """로그인 요청."""

    member_id: str
    password: str


class LoginResponse(BaseModel):
    """로그인 성공 응답."""

    member_id: str
    name: str
    type: str


class LogoutResponse(BaseModel):
    """로그아웃 응답."""

    ok: bool


class MeResponse(BaseModel):
    """현재 사용자 정보 응답."""

    member_id: str
    name: str
    type: str
    emoji: str = ""
    role: str = ""
    login_at: str = ""


# ── 봇 ──────────────────────────────────────────────


class BotListResponse(BaseModel):
    """봇 목록 응답."""

    bots: list[dict[str, Any]]
    next_cursor: str | None = None


class BotDetailResponse(BaseModel):
    """봇 상세/생성/시작/중지 응답."""

    bot: dict[str, Any]


# ── 전략 ──────────────────────────────────────────────


class StrategyValidateResponse(BaseModel):
    """전략 검증 응답."""

    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class StrategyListItem(BaseModel):
    """전략 목록 아이템."""

    id: str
    name: str
    version: str
    status: str
    author: str
    bot_id: str | None = None
    bot_status: str | None = None


class StrategyListResponse(BaseModel):
    """전략 목록 응답."""

    strategies: list[StrategyListItem]


class StrategyDetailResponse(BaseModel):
    """전략 상세 응답."""

    strategy: dict[str, Any]
    bot: dict[str, Any] | None = None


class EquityCurvePoint(BaseModel):
    """에쿼티 커브 포인트."""

    date: str
    value: float


class StrategyPerformanceResponse(BaseModel):
    """전략 성과 지표 응답."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: list[dict[str, Any]] = []

    model_config = ConfigDict(extra="allow")  #


class DailySummaryItem(BaseModel):
    """일별 성과 집계 아이템."""

    date: str
    realized_pnl: float
    trade_count: int
    win_rate: float


class DailySummaryResponse(BaseModel):
    """일별 성과 집계 응답."""

    items: list[DailySummaryItem]


class WeeklySummaryItem(BaseModel):
    """주별 성과 집계 아이템."""

    week_start: str
    week_end: str
    week_label: str
    realized_pnl: float
    trade_count: int
    win_rate: float


class WeeklySummaryResponse(BaseModel):
    """주별 성과 집계 응답."""

    items: list[WeeklySummaryItem]


class MonthlySummaryItem(BaseModel):
    """월별 성과 집계 아이템."""

    year: int
    month: int
    realized_pnl: float
    trade_count: int
    win_rate: float


class MonthlySummaryResponse(BaseModel):
    """월별 성과 집계 응답."""

    items: list[MonthlySummaryItem]


class StrategyTradeItem(BaseModel):
    """전략 거래 아이템."""

    trade_id: str
    bot_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str
    timestamp: str


class StrategyTradesResponse(BaseModel):
    """전략 거래 내역 응답."""

    trades: list[StrategyTradeItem]
    next_cursor: str | None = None


# ── Treasury ──────────────────────────────────────────────


class TreasurySummaryResponse(BaseModel):
    """자금 현황 요약 응답."""

    total_balance: float = 0.0
    unallocated: float = 0.0
    total_allocated: float = 0.0
    total_evaluation: float = 0.0
    total_profit_loss: float = 0.0
    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0023
    broker_id: str | None = None
    broker_name: str | None = None
    broker_short_name: str | None = None
    exchange: str | None = None
    account_no: str | None = None
    is_virtual: bool | None = None
    synced_at: str | None = None

    model_config = ConfigDict(extra="allow")  #


class TransactionItem(BaseModel):
    """자금 변동 이력 아이템."""

    id: int
    type: str
    bot_id: str | None = None
    amount: float
    description: str = ""
    created_at: str


class TransactionListResponse(BaseModel):
    """자금 변동 이력 응답."""

    items: list[TransactionItem]
    total: int


class BudgetOperationResponse(BaseModel):
    """예산 할당/회수 응답."""

    bot_id: str
    allocated: float
    available: float


class BudgetListResponse(BaseModel):
    """예산 목록 응답."""

    budgets: list[dict[str, Any]]


class BalanceSetResponse(BaseModel):
    """잔고 설정 응답."""

    total_balance: float
    updated_at: str


# ── 리포트 ──────────────────────────────────────────────


class ReportSubmitRequest(BaseModel):
    """리포트 제출 요청."""

    strategy_name: str
    strategy_version: str
    backtest_result: dict
    summary: str = ""
    recommendation: str = ""


class ReportSubmitResponse(BaseModel):
    """리포트 제출 응답."""

    report_id: str
    strategy: str
    status: str


class ReportDetailResponse(BaseModel):
    """리포트 상세 응답."""

    report_id: str
    strategy_name: str
    strategy_version: str
    strategy_path: str = ""
    status: str
    submitted_at: str
    submitted_by: str = ""
    backtest_period: str | None = None
    total_return_pct: float | None = None
    total_trades: int | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    summary: str = ""
    rationale: str = ""
    risks: str = ""
    recommendations: str = ""
    equity_curve: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    initial_balance: float | None = None
    final_balance: float | None = None
    symbols: list[str | dict[str, Any]] = []
    user_notes: str = ""
    reviewed_at: str | None = None


class ReportListItem(BaseModel):
    """리포트 목록 아이템."""

    report_id: str
    strategy: str
    status: str
    submitted_at: str


class ReportListResponse(BaseModel):
    """리포트 목록 응답."""

    reports: list[ReportListItem]
    next_cursor: str | None = None


class ReportSchemaResponse(BaseModel):
    """리포트 스키마 응답."""

    model_config = ConfigDict(extra="allow")  #


# ── 데이터 ──────────────────────────────────────────────


class DataInjectRequest(BaseModel):
    """데이터 주입 요청 (JSON body)."""

    symbol: str
    timeframe: str = "1d"
    source: str = "external"


class DatasetItem(BaseModel):
    """데이터셋 아이템."""

    id: str
    symbol: str
    timeframe: str
    data_type: str
    start_date: str | None = None
    end_date: str | None = None
    row_count: int = 0


class DatasetListResponse(BaseModel):
    """데이터셋 목록 응답."""

    items: list[DatasetItem]
    total: int


class DataSchemaResponse(BaseModel):
    """데이터 스키마 응답 (동적 키-값)."""

    model_config = ConfigDict(extra="allow")  #


class StorageSummaryResponse(BaseModel):
    """저장 용량 현황 응답."""

    total_bytes: int
    total_mb: float
    by_timeframe: dict[str, float]


class FeedStatusResponse(BaseModel):
    """Feed 파이프라인 상태 응답."""

    initialized: bool = False
    checkpoints: list[dict[str, Any]] = []
    recent_reports: list[dict[str, Any]] = []
    api_keys: list[dict[str, Any]] = []


# ── 멤버 ──────────────────────────────────────────────


class MemberListResponse(BaseModel):
    """멤버 목록 응답."""

    members: list[dict[str, Any]]
    total: int


class MemberDetailResponse(BaseModel):
    """멤버 상세 응답."""

    member: dict[str, Any]


class MemberCreateResponse(BaseModel):
    """멤버 생성 응답 (토큰 포함)."""

    member: dict[str, Any]
    token: str


class MemberTokenResponse(BaseModel):
    """토큰 재발급 응답."""

    member: dict[str, Any]
    token: str


class OkResponse(BaseModel):
    """단순 성공 응답."""

    ok: bool


class MemberScopesResponse(BaseModel):
    """권한 범위 변경 응답."""

    member: dict[str, Any]


# ── 거래 ──────────────────────────────────────────────


class TradeItem(BaseModel):
    """거래 기록 아이템."""

    trade_id: str
    bot_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str
    created_at: str


class TradeListResponse(BaseModel):
    """거래 기록 목록 응답."""

    trades: list[TradeItem]
    next_cursor: str | None = None


# ── 결재 ──────────────────────────────────────────────


class ApprovalListResponse(BaseModel):
    """결재 목록 응답."""

    approvals: list[dict[str, Any]]
    total: int


class ApprovalDetailResponse(BaseModel):
    """결재 상세 응답."""

    approval: dict[str, Any]
    report_detail: dict[str, Any] | None = None


class ApprovalUpdateResponse(BaseModel):
    """결재 상태 변경 응답."""

    approval: dict[str, Any]


# ── 설정 ──────────────────────────────────────────────


class ConfigListResponse(BaseModel):
    """동적 설정 목록 응답."""

    configs: list[dict[str, Any]]


class ConfigUpdateResponse(BaseModel):
    """설정 변경 응답."""

    key: str
    old_value: Any = None
    new_value: Any = None


# ── 포트폴리오 ──────────────────────────────────────────────


class PortfolioValueResponse(BaseModel):
    """총 자산 가치 응답."""

    total_value: float
    daily_pnl: float
    daily_pnl_pct: float
    updated_at: str


class PortfolioHistoryPoint(BaseModel):
    """자산 추이 데이터 포인트."""

    date: str
    value: float


class PortfolioHistoryResponse(BaseModel):
    """기간별 자산 추이 응답."""

    data: list[PortfolioHistoryPoint]
    period: str


# ── 감사 로그 ──────────────────────────────────────────────


class AuditLogListResponse(BaseModel):
    """감사 로그 목록 응답."""

    logs: list[dict[str, Any]]
    total: int


# ── 알림 ──────────────────────────────────────────────


class NotificationItem(BaseModel):
    """알림 이력 아이템."""

    id: str
    level: str
    title: str
    message: str
    success: bool
    created_at: str


class NotificationListResponse(BaseModel):
    """알림 이력 목록 응답."""

    notifications: list[NotificationItem]
    next_cursor: str | None = None


# ── 테스트 시드 ──────────────────────────────────────────────


class SeedResetResponse(BaseModel):
    """시드 리셋 응답."""

    ok: bool
    scenario: str
