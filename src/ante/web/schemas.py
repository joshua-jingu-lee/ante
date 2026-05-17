"""Web API Pydantic 요청/응답 모델."""

from __future__ import annotations

import math
import re
from datetime import time as dtime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ante import __version__
from ante.account.timezone import validate_iana_timezone

# Account `trading_hours_start`/`trading_hours_end`의 strict HH:MM 24시간 형식.
# SSOT: docs/specs/account/03-data-model.md (HH:MM), docs/specs/account/10-web-api.md.
# 초/마이크로초 포함, 빈 문자열(update만), invalid 시간은 422로 거부한다.
HH_MM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
_HH_MM_RE = re.compile(HH_MM_PATTERN)


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
    # 시장가 매수 reserve buffer 비율 (cold-path 전용 — #1333).
    market_order_reserve_buffer_rate: float = 0.0
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
    # 시장가 매수 reserve buffer 비율. omit 시 service-layer에서 BrokerPreset
    # 기본값을 사용한다. cold-path 전용 (#1333).
    market_order_reserve_buffer_rate: float | None = None

    @field_validator("trading_hours_start", "trading_hours_end")
    @classmethod
    def _validate_trading_hours_create(cls, v: str) -> str:
        """strict HH:MM 24시간 형식 검증.

        ``""``는 default 의미를 보존하기 위해 통과시킨다 — CLI/seed 경로에서
        BrokerPreset fallback이 ``""``를 preset value로 채우기 때문이다 (#1334
        plan v5: AccountCreateRequest의 ``""`` 통과는 default 의미 보존).
        non-empty 값은 regex 매치 후 ``time.fromisoformat``으로 이중 검증한다.
        """
        if v == "":
            return v
        if not _HH_MM_RE.fullmatch(v):
            raise ValueError("trading_hours는 strict HH:MM 24시간 형식이어야 합니다")
        try:
            dtime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                "trading_hours는 strict HH:MM 24시간 형식이어야 합니다"
            ) from exc
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_timezone_create(cls, v: str) -> str:
        """IANA timezone key 검증 (create 경로).

        ``""`` 는 ``trading_hours_*`` 와 동일하게 default 의미 보존을 위해
        통과시킨다 — CLI/seed 경로에서 BrokerPreset fallback 이 ``""`` 를
        preset value 로 채우기 때문이다. non-empty 값은
        :func:`ante.account.timezone.validate_iana_timezone` 으로 검증한다
        (#1473 split #1419/A).
        """
        if v == "":
            return v
        # 공유 helper(account/timezone.py)는 service caller 보존을 위해
        # 미변경. web 422 경계에서만 거부값을 반사하지 않도록 wrap 한다
        # (보안 invariant #1629 L1 반사 경로 2 — helper 위임 경로).
        try:
            return validate_iana_timezone(v)
        except ValueError as exc:
            raise ValueError("timezone은 유효한 IANA timezone이어야 합니다") from exc


class AccountUpdateRequest(BaseModel):
    """계좌 수정 요청.

    하위 호환을 위해 모든 필드를 옵션으로 노출하지만, 런타임 PUT 라우트는
    structural 필드를 cold-path로 차단한다. 이 모델은 다른 소비자(테스트,
    CLI 등)와의 하위 호환을 위해 유지한다. PUT requestBody의 schema accuracy
    회복(mutable 모델 노출)은 후속 이슈 #1143에서 다룬다.
    """

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
    # 다른 structural 필드와 동일하게 모델에는 노출하지만, PUT 라우트는
    # ``STRUCTURAL_FIELDS`` 가드로 cold-path 409 차단한다 (#1333).
    market_order_reserve_buffer_rate: float | None = None

    @field_validator("trading_hours_start", "trading_hours_end")
    @classmethod
    def _validate_trading_hours_update(cls, v: str | None) -> str | None:
        """strict HH:MM 24시간 형식 검증 (update 경로).

        ``None``은 통과(필드 미제공). 그 외(``""`` 포함)는 regex + fromisoformat
        검증 — update 경로는 broker preset fallback이 없기 때문이다 (#1334).
        실패 시 ``ValueError``로 422 Unprocessable Entity를 유도한다.
        """
        if v is None:
            return v
        if not _HH_MM_RE.fullmatch(v):
            raise ValueError("trading_hours는 strict HH:MM 24시간 형식이어야 합니다")
        try:
            dtime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                "trading_hours는 strict HH:MM 24시간 형식이어야 합니다"
            ) from exc
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_timezone_update(cls, v: str | None) -> str | None:
        """IANA timezone key 검증 (update 경로).

        ``None`` 은 통과(필드 미제공). 그 외(``""`` 포함)는
        :func:`ante.account.timezone.validate_iana_timezone` 으로 검증 — update
        경로는 broker preset fallback 이 없으므로 ``""`` 도 invalid 다
        (``trading_hours_*`` update validator 패턴 일치, #1473 split #1419/A).
        실패 시 ``ValueError`` 로 422 Unprocessable Entity 를 유도한다.
        """
        if v is None:
            return v
        # 공유 helper(account/timezone.py)는 service caller 보존을 위해
        # 미변경. web 422 경계에서만 거부값을 반사하지 않도록 wrap 한다
        # (보안 invariant #1629 L1 반사 경로 2 — helper 위임 경로).
        try:
            return validate_iana_timezone(v)
        except ValueError as exc:
            raise ValueError("timezone은 유효한 IANA timezone이어야 합니다") from exc


class AccountSuspendRequest(BaseModel):
    """계좌 정지 요청.

    OpenAPI ``additionalProperties`` 정합성을 위해 ``extra="forbid"``로 미지정
    필드를 거부한다(#1352 — Codex Plan Review). 같은 PR에서 ``BotUpdateRequest``,
    ``BalanceSetRequest``도 동일 정책을 적용해 5개 mutation route 입력 contract
    drift를 예방한다.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = ""


class AccountActionResponse(BaseModel):
    """계좌 상태 변경 응답."""

    account: AccountResponse
    message: str


# ── 시스템 ──────────────────────────────────────────────


class StatusResponse(BaseModel):
    """시스템 상태 응답."""

    status: str
    version: str = __version__
    trading_status: str | None = None
    halt_time: str | None = None
    halt_reason: str | None = None


class HealthResponse(BaseModel):
    """헬스체크 응답.

    - `ok`: 모든 의존성 체크 통과 여부 (`all(checks.values())`).
    - `checks`: 개별 의존성 체크 결과. 1.0 기준 키는 `db`, `broker`.
      키 확장은 하위 호환이므로 소비자는 존재하는 키만 확인한다.

    `ok`와 `checks` 모두 필수 필드 (OpenAPI `required`).
    """

    ok: bool
    checks: dict[str, bool]


class KillSwitchAccountChange(BaseModel):
    """킬 스위치 처리 대상 계좌의 상태 전환 결과.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 필드 표.
    필드는 정확히 ``account_id``, ``previous_status``, ``status``, ``changed`` 4개
    키만 사용한다 (``before_status`` / ``after_status`` 사용 금지).
    """

    account_id: str
    previous_status: str
    status: str
    changed: bool


class KillSwitchResponse(BaseModel):
    """킬 스위치 제어 응답.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답.

    - ``POST /api/system/halt`` → ``status="halted"``
    - ``POST /api/system/clear-halt`` → ``status="halt_cleared"``
    """

    status: str
    accounts_changed: int
    changed_at: str
    accounts: list[KillSwitchAccountChange] = []


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


class BotConfigOut(BaseModel):
    """봇 runtime control 6 필드 nested 응답 (#1458).

    ``GET /api/bots/{bot_id}`` 응답에 nested 객체 ``config`` 로 직렬화되어
    대시보드 BotDetail edit modal prefill 의 SSOT 가 된다.
    ``docs/dashboard/user-stories/bots.md`` B-3/B-5 line 197-200 의 6 필드
    (``interval_seconds``, ``auto_restart``, ``max_restart_attempts``,
    ``restart_cooldown_seconds``, ``step_timeout_seconds``,
    ``max_signals_per_step``) 만 노출하며 다른 키는 ``extra="forbid"`` 로
    차단한다 (강한 schema 계약).
    """

    model_config = ConfigDict(extra="forbid")

    interval_seconds: int
    auto_restart: bool
    max_restart_attempts: int
    restart_cooldown_seconds: int
    step_timeout_seconds: int
    max_signals_per_step: int


class BotInfo(BaseModel):
    """봇 정보 (read 응답).

    write 경로(``BotConfig``, ``ApprovalService.create``)에서 account_id가
    검증되므로 read 응답 schema에는 default를 유지한다.

    ``config`` (`BotConfigOut`) 는 #1458 에서 추가된 runtime control 6 필드
    nested 객체다. backward compatibility 를 위해 top-level ``interval_seconds``
    는 유지하되, 다른 runtime control 필드는 top-level 에 노출하지 않는다
    (계약 중복 방지).
    """

    bot_id: str
    name: str = ""
    status: str = ""
    account_id: str = ""
    strategy_id: str = ""
    strategy_name: str | None = None
    strategy_author_name: str | None = None
    strategy_author_id: str | None = None
    interval_seconds: int = 60
    started_at: str | None = None
    stopped_at: str | None = None
    error_message: str | None = None
    config: BotConfigOut | None = None

    # 봇 상세 조회 시 추가되는 동적 필드 (strategy, budget, positions 등)
    model_config = ConfigDict(extra="allow")


class BotUpdateRequest(BaseModel):
    """봇 설정 수정 요청. None인 필드는 변경하지 않는다.

    OpenAPI ``BOT_UPDATE_REQUEST_SCHEMA``는 ``additionalProperties: false``를
    선언한다. 런타임 모델도 ``extra="forbid"``로 동일하게 강제해 OpenAPI
    contract와 동작을 일치시킨다(#1352 — Codex Plan Review).

    runtime control 4개 필드 (``max_restart_attempts``,
    ``restart_cooldown_seconds``, ``step_timeout_seconds``,
    ``max_signals_per_step``) 는 ``docs/dashboard/user-stories/bots.md``
    B-5 line 197-200 spec 범위 안에서만 허용된다 (#1456). 범위 밖 값은
    ``ValidationError`` 로 거부되어 PUT 핸들러에서 422 가 반환된다.
    ``BotConfig`` 단의 ``validate_runtime_controls`` 와 정합한다.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    strategy_name: str | None = None
    interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    budget: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    auto_restart: bool | None = None
    max_restart_attempts: int | None = Field(default=None, ge=1, le=10)
    restart_cooldown_seconds: int | None = Field(default=None, ge=10, le=600)
    step_timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    max_signals_per_step: int | None = Field(default=None, ge=1, le=200)


class BotListResponse(BaseModel):
    """봇 목록 응답."""

    bots: list[BotInfo]
    next_cursor: str | None = None


class BotDetailResponse(BaseModel):
    """봇 상세/생성/시작/중지 응답."""

    bot: BotInfo


# ── 전략 ──────────────────────────────────────────────


class StatusUpdateRequest(BaseModel):
    """전략 상태 변경 요청.

    SSOT: ``docs/specs/web-api/05-resource-endpoints.md`` PATCH
    ``/api/strategies/{strategy_id}/status``. ``status`` 는 transition 가능한
    상태만 허용한다 — ``registered`` 는 등록 시점 초기값이므로 PATCH 의
    target 이 아니다 (GET filter 의 ``_VALID_STATUS_FILTERS`` 와는 별도).

    invariants (#1441):
    - ``model_config = ConfigDict(extra="forbid")`` — 정의되지 않은 필드는
      Pydantic 단에서 422 로 거부 (handler 도달 차단). OpenAPI 에서는
      ``additionalProperties: false`` 로 노출되어 generated TS client 가
      closed object type 으로 좁힌다.
    - ``status: Literal["adopted", "archived"]`` — transition target 만
      enum 으로 노출. ``registered`` / 임의 문자열 / type mismatch 는 422.
      handler 의 enum 변환 분기는 defense-in-depth 로 ``StrategyStatus``
      registry transition rule (예: archived → adopted 차단) 만 다룬다.
    """

    model_config = ConfigDict(extra="forbid")
    status: Literal["adopted", "archived"]


class StrategyValidateRequest(BaseModel):
    """전략 검증 요청.

    SSOT: ``docs/specs/web-api/05-resource-endpoints.md`` POST
    ``/api/strategies/validate`` body ``{"path": "..."}``. ``path`` 타입이
    string 이 아니면 Pydantic 이 422 로 거부한다 (#1410 — non-string
    ``path`` 입력에서 ``Path(filepath)`` TypeError 로 500 이 반환되던 회귀를
    runtime validation 으로 차단).
    """

    path: str


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
    author_name: str = "agent"
    author_id: str = "agent"
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
    author_name: str = "agent"
    author_id: str = "agent"
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
    """리포트 제출 요청.

    SSOT: ``docs/specs/report-store/report-store.md`` 리포트 제출 스키마.
    ``win_rate``는 percent 단위 (0.0~100.0, ``"win_rate": 58.0`` 예시)다.

    invariants (#1353):
    - ``total_trades >= 0`` (거래 수는 음수 불가).
    - ``win_rate``는 ``[0.0, 100.0]`` percent 단위 또는 ``None``.
    - ``total_return_pct``/``sharpe_ratio``/``max_drawdown_pct``/``win_rate``는
      finite. NaN/Inf는 후속 분석/표시에서 버그 또는 잘못된 결정으로 이어지므로
      submit 단에서 422로 거부한다.
    - 미지정 키는 ``extra='forbid'``로 거부 — agent의 오타/잘못된 키가 store에
      유실되는 대신 빠르게 fail하도록 한다.

    Note: 단위 통일(percent ↔ ratio)은 detail_json·backtest_runs·CLI submit 등
    시스템 전반의 영향이 커서 본 PR에서는 input validation에만 집중하고,
    ratio 통일은 별도 follow-up 이슈에서 다룬다.
    """

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    strategy_version: str
    strategy_path: str
    backtest_period: str
    total_return_pct: float = Field(allow_inf_nan=False)
    total_trades: int = Field(ge=0)
    sharpe_ratio: float | None = Field(default=None, allow_inf_nan=False)
    max_drawdown_pct: float | None = Field(default=None, allow_inf_nan=False)
    win_rate: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    summary: str
    rationale: str
    risks: str = ""
    recommendations: str = ""
    detail_json: str = "{}"


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
    config: dict[str, Any] | None = None
    datasets: list[dict[str, Any]] = []
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
    """멤버 정보 (공개 응답 노출 계약 — `docs/specs/member/03-member-model.md`).

    `token_hash`/`password_hash`/`recovery_key_hash`는 credential verifier
    material 이므로 응답 schema·runtime body 어디에도 노출하지 않는다 (#1627).
    """

    member_id: str
    type: str
    role: str
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = []
    created_at: str = ""
    created_by: str = ""
    last_active_at: str = ""
    suspended_at: str = ""
    revoked_at: str = ""
    token_expires_at: str = ""

    # Member dataclass 변환 시 임의 extra 필드(hash 포함)는 validation
    # error 없이 받되 **출력에서 drop** 한다. `extra="allow"` 는 extra 키를
    # 응답으로 그대로 echo 하므로 credential hash 누출 트랩이 된다 (#1627).
    model_config = ConfigDict(extra="ignore")


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
    """거래 기록 아이템 (read 응답).

    write 경로(``TradeRecord``)에서 account_id가 검증되므로 read 응답
    schema에는 default를 유지한다.
    """

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


# ``RuleUpdateRequest.params`` 는 룰별로 schema 가 다른 ``dict[str, Any]`` open
# object 다 (OpenAPI ``additionalProperties: true``). 하지만 모든 룰의 numeric
# threshold 는 finite real number 여야 한다 — ``NaN`` / ``Inf`` 는 비교 의미가
# 없어 fail-open 회귀나 ``json.dumps`` 직렬화 후 다운스트림 파싱 에러를 유발한다
# (#1380 oracle A7). 본 helper 는 finite/Inf 검증을 ``params`` 트리 전체에 재귀
# 적용하여 service 경계에서 422 로 잘라낸다. RULE_REGISTRY 단의 finite 검사는
# 이중 방어로 따로 둔다.
def _reject_non_finite(value: Any) -> None:
    """``params`` 트리 안에 ``NaN`` / ``Inf`` numeric 이 있으면 ``ValueError``.

    - ``bool`` → 통과 (``isinstance(True, int) == True`` 이므로 numeric 분기에서
      가로채면 안 된다 — bool 정책은 RULE_REGISTRY ``validate_config`` 에서
      별도로 거부한다).
    - ``int`` / ``float`` → ``math.isnan`` / ``math.isinf`` 검사. Python ``int``
      는 임의 정밀도라 ``10**10000`` 같은 거대 정수 ``float`` 변환에서
      ``OverflowError`` 가 떨어질 수 있다 (``rule/engine.py:69-80``
      ``_is_finite_quantity`` 패턴 참조). ``OverflowError`` / ``ValueError`` /
      ``TypeError`` 는 finite-호환이 아니므로 동일하게 ``ValueError`` 로 매핑한다.
    - ``dict`` / ``list`` / ``tuple`` → 요소 재귀.
    - 그 외 (``str``, ``None`` 등) → 통과 (numeric 검증 대상 아님).
    """
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        try:
            if math.isnan(value) or math.isinf(value):
                raise ValueError(
                    "params 의 numeric 값은 finite 여야 합니다 (NaN/Inf 거부)."
                )
        except (OverflowError, TypeError) as exc:
            raise ValueError(
                "params 의 numeric 값은 finite 여야 합니다 (NaN/Inf 거부)."
            ) from exc
        return
    if isinstance(value, dict):
        for v in value.values():
            _reject_non_finite(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _reject_non_finite(v)
        return


class RuleUpdateRequest(BaseModel):
    """룰 설정 변경 요청.

    ``params`` 는 룰별 schema 를 갖는 open object 지만, 모든 numeric threshold
    는 finite 여야 한다 (#1380 oracle A7). ``json.loads`` default 는 ``NaN`` /
    ``Infinity`` / ``-Infinity`` 를 ``float('nan')`` / ``float('inf')`` 로
    파싱하므로, raw body parser 가 통과시킨 값을 본 모델 단에서 422 로 거부한다.
    bool 은 numeric 흉내 방지를 위해 ``_reject_non_finite`` 가 통과시키되,
    RULE_REGISTRY ``validate_config`` 가 known numeric key 에 대해 별도로
    거부한다.
    """

    enabled: bool = True
    params: dict[str, Any] = {}

    @field_validator("params")
    @classmethod
    def _validate_params_finite(cls, v: dict[str, Any]) -> dict[str, Any]:
        """``params`` 트리에서 ``NaN`` / ``Inf`` numeric 을 거부.

        실패 시 ``ValueError`` 를 raise 하여 FastAPI 가 ``ValidationError`` →
        422 로 매핑하도록 한다 (#1380).
        """
        _reject_non_finite(v)
        return v


class RuleUpdateResponse(BaseModel):
    """룰 설정 변경 응답."""

    account_id: str
    rule_type: str
    rule: RuleItem
