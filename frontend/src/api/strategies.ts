import client from './client'
import type {
  DailySummaryItem as ApiDailySummaryItem,
  DailySummaryResponse as ApiDailySummaryResponse,
  MonthlySummaryItem as ApiMonthlySummaryItem,
  MonthlySummaryResponse as ApiMonthlySummaryResponse,
  StatusUpdateRequest as ApiStatusUpdateRequest,
  StrategyDetailResponse as ApiStrategyDetailResponse,
  StrategyInfo as ApiStrategyInfo,
  StrategyListItem as ApiStrategyListItem,
  StrategyListResponse as ApiStrategyListResponse,
  StrategyPerformanceResponse as ApiStrategyPerformanceResponse,
  StrategyTradeItem as ApiStrategyTradeItem,
  StrategyTradesResponse as ApiStrategyTradesResponse,
  WeeklySummaryItem as ApiWeeklySummaryItem,
  WeeklySummaryResponse as ApiWeeklySummaryResponse,
} from '../types/api.generated'
import type { Strategy, StrategyDetail, StrategyPerformance, Trade, DailySummary, WeeklySummary, MonthlySummary } from '../types/strategy'

function toRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function toOptionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function toEquityCurve(value: unknown): { date: string; value: number }[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const row = toRecord(item)
    const date = toOptionalString(row.date) ?? toOptionalString(row.timestamp)
    const pointValue = toOptionalNumber(row.value) ?? toOptionalNumber(row.equity) ?? toOptionalNumber(row.balance)
    return date && pointValue != null ? [{ date, value: pointValue }] : []
  })
}

function toStrategyListItem(raw: ApiStrategyListItem): Strategy {
  return {
    id: raw.id,
    name: raw.name,
    version: raw.version,
    status: raw.status,
    author_name: raw.author_name,
    author_id: raw.author_id,
    bot_id: raw.bot_id,
    bot_status: raw.bot_status,
    cumulative_return: raw.cumulative_return ?? undefined,
  }
}

function toStrategyDetailView(
  raw: ApiStrategyInfo,
  detail: ApiStrategyDetailResponse,
): StrategyDetail {
  return {
    id: raw.strategy_id,
    name: raw.name,
    version: raw.version,
    status: detail.status ?? raw.status,
    author_name: raw.author_name,
    author_id: raw.author_id,
    bot_id: detail.bot?.bot_id,
    bot_status: detail.bot?.status,
    created_at: raw.registered_at,
    description: raw.description,
    rationale: detail.rationale || raw.rationale,
    risks: detail.risks.length > 0 ? detail.risks : raw.risks,
    params: detail.params,
    param_schema: detail.param_schema,
    budget_allocated: toOptionalNumber(raw.budget_allocated),
    unrealized_pnl: toOptionalNumber(raw.unrealized_pnl),
  }
}

function toStrategyPerformanceView(raw: ApiStrategyPerformanceResponse): StrategyPerformance {
  return {
    total_trades: raw.total_trades,
    winning_trades: raw.winning_trades,
    losing_trades: raw.losing_trades,
    win_rate: raw.win_rate,
    total_pnl: raw.total_pnl,
    total_commission: toOptionalNumber(raw.total_commission),
    net_pnl: toOptionalNumber(raw.net_pnl),
    avg_profit: toOptionalNumber(raw.avg_profit),
    avg_loss: toOptionalNumber(raw.avg_loss),
    avg_pnl: raw.avg_pnl,
    profit_factor: raw.profit_factor,
    max_drawdown: raw.max_drawdown,
    max_drawdown_amount: toOptionalNumber(raw.max_drawdown_amount),
    sharpe_ratio: raw.sharpe_ratio,
    active_days: toOptionalNumber(raw.active_days),
    realized_pnl: toOptionalNumber(raw.realized_pnl),
    unrealized_pnl: toOptionalNumber(raw.unrealized_pnl),
    budget_allocated: toOptionalNumber(raw.budget_allocated),
    equity_curve: toEquityCurve(raw.equity_curve),
  }
}

function toTrade(raw: ApiStrategyTradeItem): Trade {
  return {
    id: raw.trade_id,
    trade_id: raw.trade_id,
    bot_id: raw.bot_id,
    symbol: raw.symbol,
    side: raw.side,
    quantity: raw.quantity,
    price: raw.price,
    executed_at: raw.timestamp,
    timestamp: raw.timestamp,
    status: raw.status,
  }
}

function toDailySummary(raw: ApiDailySummaryItem): DailySummary {
  return {
    date: raw.date,
    realized_pnl: raw.realized_pnl,
    trade_count: raw.trade_count,
    win_rate: raw.win_rate,
  }
}

function toWeeklySummary(raw: ApiWeeklySummaryItem): WeeklySummary {
  return {
    week_start: raw.week_start,
    week_end: raw.week_end,
    week_label: raw.week_label,
    realized_pnl: raw.realized_pnl,
    trade_count: raw.trade_count,
    win_rate: raw.win_rate,
  }
}

function toMonthlySummary(raw: ApiMonthlySummaryItem): MonthlySummary {
  return {
    year: raw.year,
    month: raw.month,
    realized_pnl: raw.realized_pnl,
    trade_count: raw.trade_count,
    win_rate: raw.win_rate,
  }
}

export async function getStrategies(params?: { search?: string }): Promise<Strategy[]> {
  const res = await client.get<ApiStrategyListResponse>('/api/strategies', { params })
  return res.data.strategies.map(toStrategyListItem)
}

export async function getStrategyDetail(id: string): Promise<StrategyDetail> {
  const res = await client.get<ApiStrategyDetailResponse>(`/api/strategies/${id}`)
  return toStrategyDetailView(res.data.strategy, res.data)
}

export async function getStrategyPerformance(id: string): Promise<StrategyPerformance> {
  const res = await client.get<ApiStrategyPerformanceResponse>(`/api/strategies/${id}/performance`)
  return toStrategyPerformanceView(res.data)
}

export async function getStrategyTrades(
  id: string,
  params?: { cursor?: number; limit?: number },
): Promise<{ items: Trade[]; next_cursor?: number }> {
  const res = await client.get<ApiStrategyTradesResponse>(`/api/strategies/${id}/trades`, { params })
  const nextCursor = res.data.next_cursor != null ? Number(res.data.next_cursor) : undefined
  return {
    items: res.data.trades.map(toTrade),
    next_cursor: Number.isFinite(nextCursor) ? nextCursor : undefined,
  }
}

export async function getStrategyDailySummary(id: string): Promise<DailySummary[]> {
  const res = await client.get<ApiDailySummaryResponse>(`/api/strategies/${id}/daily-summary`)
  return res.data.items.map(toDailySummary)
}

export async function getStrategyWeeklySummary(id: string): Promise<WeeklySummary[]> {
  const res = await client.get<ApiWeeklySummaryResponse>(`/api/strategies/${id}/weekly-summary`)
  return res.data.items.map(toWeeklySummary)
}

export async function getStrategyMonthlySummary(id: string): Promise<MonthlySummary[]> {
  const res = await client.get<ApiMonthlySummaryResponse>(`/api/strategies/${id}/monthly-summary`)
  return res.data.items.map(toMonthlySummary)
}

export type StrategyStatusTransition = ApiStatusUpdateRequest['status']

export async function updateStrategyStatus(
  id: string,
  status: StrategyStatusTransition,
): Promise<void> {
  // generated type narrowing (#1441): `status` 는 `'adopted' | 'archived'`
  // 로 좁혀져 transition target 만 허용한다 — `registered` 등 GET filter
  // 전용 값은 컴파일 시점에 차단된다.
  const payload: ApiStatusUpdateRequest = { status }
  await client.patch<ApiStrategyDetailResponse>(`/api/strategies/${id}/status`, payload)
}

export async function getStrategyTradesPaginated(
  id: string,
  params?: { offset?: number; limit?: number; side?: string; start_date?: string; end_date?: string },
): Promise<{ items: Trade[]; total: number }> {
  const res = await client.get<ApiStrategyTradesResponse>(`/api/strategies/${id}/trades`, { params })
  return {
    items: res.data.trades.map(toTrade),
    total: toNumber(toRecord(res.data).total, res.data.trades.length),
  }
}
