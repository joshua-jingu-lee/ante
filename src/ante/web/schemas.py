"""Web API Pydantic 요청/응답 모델."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details 에러 응답."""

    type: str = "/errors/internal"
    title: str = "Internal Server Error"
    detail: str = ""
    status: int = 500
    instance: str = ""


# ── 계좌 ──────────────────────────────────────────────


class AccountResponse(BaseModel):
    """계좌 응답. credentials는 보안상 포함하지 않는다."""

    account_id: str
    name: str
    exchange: str
    currency: str
    timezone: str
    trading_hours_start: str
    trading_hours_end: str
    trading_mode: str
    broker_type: str
    broker_config: dict[str, Any] = {}
    buy_commission_rate: float
    sell_commission_rate: float
    status: str
    created_at: str
    updated_at: str


class AccountListResponse(BaseModel):
    """계좌 목록 응답."""

    accounts: list[AccountResponse]


class AccountDetailResponse(BaseModel):
    """계좌 상세 응답."""

    account: AccountResponse


class AccountCreateRequest(BaseModel):
    """계좌 생성 요청."""

    account_id: str
    name: str
    exchange: str = ""
    currency: str = ""
    timezone: str = ""
    trading_hours_start: str = ""
    trading_hours_end: str = ""
    trading_mode: str = "virtual"
    broker_type: str = "test"
    credentials: dict[str, str] = {}
    broker_config: dict[str, Any] = {}
    buy_commission_rate: float = 0.0
    sell_commission_rate: float = 0.0


class AccountUpdateRequest(BaseModel):
    """계좌 수정 요청."""

    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    timezone: str | None = None
    trading_hours_start: str | None = None
    trading_hours_end: str | None = None
    trading_mode: str | None = None
    broker_type: str | None = None
    credentials: dict[str, str] | None = None
    broker_config: dict[str, Any] | None = None
    buy_commission_rate: float | None = None
    sell_commission_rate: float | None = None


class AccountSuspendRequest(BaseModel):
    """계좌 정지 요청."""

    reason: str = ""


class AccountActionResponse(BaseModel):
    """계좌 상태 변경 응답."""

    account: AccountResponse
    message: str


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


class BotInfo(BaseModel):
    """봇 정보."""

    bot_id: str
    name: str = ""
    status: str = ""
    account_id: str = ""
    strategy_id: str = ""
    strategy_name: str | None = None
    strategy_author_name: str | None = None
    interval_seconds: int = 60
    started_at: str | None = None
    stopped_at: str | None = None
    error_message: str | None = None

    # 봇 상세 조회 시 추가되는 동적 필드 (strategy, budget, positions 등)
    model_config = ConfigDict(extra="allow")


class BotUpdateRequest(BaseModel):
    """봇 설정 수정 요청. None인 필드는 변경하지 않는다."""

    name: str | None = None
    strategy_name: str | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    budget: float | None = Field(default=None, gt=0)
    auto_restart: bool | None = None
    max_restart_attempts: int | None = None
    restart_cooldown_seconds: int | None = None
    step_timeout_seconds: int | None = None
    max_signals_per_step: int | None = None


class BotListResponse(BaseModel):
    """봇 목록 응답."""

    bots: list[BotInfo]
    next_cursor: str | None = None


class BotDetailResponse(BaseModel):
    """봇 상세/생성/시작/중지 응답."""

    bot: BotInfo


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
    cumulative_return: float | None = None


class StrategyListResponse(BaseModel):
    """전략 목록 응답."""

    strategies: list[StrategyListItem]


class StrategyInfo(BaseModel):
    """전략 상세 정보."""

    strategy_id: str
    name: str
    version: str
    filepath: str = ""
    status: str = ""
    registered_at: str = ""
    description: str = ""
    author: str = "agent"
    validation_warnings: list[str] = []
    rationale: str = ""
    risks: list[str] = []

    # asdict(StrategyRecord) 변환 시 추가 필드 허용
    model_config = ConfigDict(extra="allow")


class StrategyDetailResponse(BaseModel):
    """전략 상세 응답."""

    strategy: StrategyInfo
    bot: BotInfo | None = None
    status: str | None = None
    params: dict[str, Any] = {}
    param_schema: dict[str, str] = {}
    rationale: str = ""
    risks: list[str] = []


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

    # 전략별 커스텀 지표가 추가될 수 있어 동적 필드 허용
    model_config = ConfigDict(extra="allow")


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

    # 브로커 연동 시 추가 메타데이터가 동적으로 포함됨
    model_config = ConfigDict(extra="allow")


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


class BudgetItem(BaseModel):
    """봇별 예산 아이템."""

    bot_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: str = ""

    # BotBudget 변환 시 추가 필드 허용
    model_config = ConfigDict(extra="allow")


class BudgetListResponse(BaseModel):
    """예산 목록 응답."""

    budgets: list[BudgetItem]


class BalanceSetResponse(BaseModel):
    """잔고 설정 응답."""

    total_balance: float
    updated_at: str


class SnapshotItem(BaseModel):
    """일별 자산 스냅샷 아이템."""

    account_id: str
    snapshot_date: str
    total_asset: float
    ante_eval_amount: float
    ante_purchase_amount: float
    unallocated: float
    account_balance: float
    total_allocated: float
    bot_count: int
    daily_pnl: float
    daily_return: float
    net_trade_amount: float
    unrealized_pnl: float
    created_at: str

    model_config = ConfigDict(extra="allow")


class SnapshotResponse(BaseModel):
    """단일 스냅샷 응답."""

    snapshot: SnapshotItem


class SnapshotListResponse(BaseModel):
    """스냅샷 목록 응답."""

    snapshots: list[SnapshotItem]


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

    # 리포트 스키마 구조가 전략 유형에 따라 달라지므로 동적 필드 허용
    model_config = ConfigDict(extra="allow")


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
    file_size: int = 0


class DatasetListResponse(BaseModel):
    """데이터셋 목록 응답."""

    items: list[DatasetItem]
    total: int


class DatasetDetailResponse(BaseModel):
    """데이터셋 상세 응답 (메타데이터 + 미리보기)."""

    dataset: DatasetItem
    preview: list[dict[str, Any]] = []


class DataSchemaResponse(BaseModel):
    """데이터 스키마 응답 (동적 키-값)."""

    # OHLCV/fundamental 등 데이터 유형별 스키마 키가 다르므로 동적 필드 허용
    model_config = ConfigDict(extra="allow")


class StorageSummaryResponse(BaseModel):
    """저장 용량 현황 응답."""

    total_bytes: int
    total_mb: float
    by_timeframe: dict[str, float]
    by_data_type: dict[str, float] | None = None


class FeedStatusResponse(BaseModel):
    """Feed 파이프라인 상태 응답."""

    initialized: bool = False
    checkpoints: list[dict[str, Any]] = []
    recent_reports: list[dict[str, Any]] = []
    api_keys: list[dict[str, Any]] = []


# ── 멤버 ──────────────────────────────────────────────


class MemberInfo(BaseModel):
    """멤버 정보."""

    member_id: str
    type: str
    role: str
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = []
    token_hash: str = ""
    password_hash: str = ""
    recovery_key_hash: str = ""
    created_at: str = ""
    created_by: str = ""
    last_active_at: str = ""
    suspended_at: str = ""
    revoked_at: str = ""
    token_expires_at: str = ""

    # Member dataclass 변환 시 추가 필드 허용
    model_config = ConfigDict(extra="allow")


class MemberListResponse(BaseModel):
    """멤버 목록 응답."""

    members: list[MemberInfo]
    total: int


class MemberDetailResponse(BaseModel):
    """멤버 상세 응답."""

    member: MemberInfo


class MemberCreateResponse(BaseModel):
    """멤버 생성 응답 (토큰 포함)."""

    member: MemberInfo
    token: str


class MemberTokenResponse(BaseModel):
    """토큰 재발급 응답."""

    member: MemberInfo
    token: str


class OkResponse(BaseModel):
    """단순 성공 응답."""

    ok: bool


class MemberScopesResponse(BaseModel):
    """권한 범위 변경 응답."""

    member: MemberInfo


# ── 거래 ──────────────────────────────────────────────


class TradeItem(BaseModel):
    """거래 기록 아이템."""

    trade_id: str
    bot_id: str
    account_id: str = ""
    symbol: str
    side: str
    quantity: float
    price: float
    status: str
    timestamp: str | None = None


class TradeListResponse(BaseModel):
    """거래 기록 목록 응답."""

    trades: list[TradeItem]
    next_cursor: str | None = None


# ── 결재 ──────────────────────────────────────────────


class ApprovalItem(BaseModel):
    """결재 요청 아이템."""

    id: str
    type: str
    status: str
    requester: str
    title: str
    body: str = ""
    params: dict[str, Any] = {}
    reviews: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    reference_id: str = ""
    expires_at: str = ""
    created_at: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
    reject_reason: str = ""

    # ApprovalRequest dataclass 변환 시 추가 필드 허용
    model_config = ConfigDict(extra="allow")


class ApprovalListResponse(BaseModel):
    """결재 목록 응답."""

    approvals: list[ApprovalItem]
    total: int


class ApprovalDetailResponse(BaseModel):
    """결재 상세 응답."""

    approval: ApprovalItem
    report_detail: dict[str, Any] | None = None


class ApprovalUpdateResponse(BaseModel):
    """결재 상태 변경 응답."""

    approval: ApprovalItem


# ── 설정 ──────────────────────────────────────────────


class ConfigItem(BaseModel):
    """동적 설정 아이템."""

    key: str
    value: Any = None
    category: str = ""
    updated_at: str = ""

    # 설정 항목별 추가 메타데이터 허용
    model_config = ConfigDict(extra="allow")


class ConfigListResponse(BaseModel):
    """동적 설정 목록 응답."""

    configs: list[ConfigItem]


class ConfigUpdateResponse(BaseModel):
    """설정 변경 응답."""

    key: str
    old_value: Any = None
    new_value: Any = None


# ── 포트폴리오 ──────────────────────────────────────────────


class PortfolioValueResponse(BaseModel):
    """총 자산 가치 응답 (스냅샷 기반)."""

    total_value: float
    daily_pnl: float
    daily_return: float
    unrealized_pnl: float = 0.0
    snapshot_date: str | None = None
    updated_at: str


class PortfolioHistoryPoint(BaseModel):
    """자산 추이 데이터 포인트 (스냅샷 기반)."""

    date: str
    total_asset: float
    daily_pnl: float
    daily_return: float
    unrealized_pnl: float


class PortfolioHistoryResponse(BaseModel):
    """기간별 자산 추이 응답."""

    data: list[PortfolioHistoryPoint]
    start_date: str
    end_date: str


# ── 감사 로그 ──────────────────────────────────────────────


class AuditLogItem(BaseModel):
    """감사 로그 아이템."""

    id: int
    member_id: str = ""
    action: str = ""
    resource: str = ""
    detail: str = ""
    ip: str = ""
    created_at: str = ""

    # 감사 로그 확장 필드 허용
    model_config = ConfigDict(extra="allow")


class AuditLogListResponse(BaseModel):
    """감사 로그 목록 응답."""

    logs: list[AuditLogItem]
    total: int


# ── 테스트 시드 ──────────────────────────────────────────────


class SeedResetResponse(BaseModel):
    """시드 리셋 응답."""

    ok: bool
    scenario: str


# ── 리스크 룰 ──────────────────────────────────────────────


class RuleItem(BaseModel):
    """룰 설정 아이템."""

    type: str
    enabled: bool = True
    params: dict[str, Any] = {}


class RuleListResponse(BaseModel):
    """계좌 룰 목록 응답."""

    account_id: str
    rules: list[RuleItem]


class RuleUpdateRequest(BaseModel):
    """룰 설정 변경 요청."""

    enabled: bool = True
    params: dict[str, Any] = {}


class RuleUpdateResponse(BaseModel):
    """룰 설정 변경 응답."""

    account_id: str
    rule_type: str
    rule: RuleItem
