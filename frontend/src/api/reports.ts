import client from './client'
import type { ReportDetailResponse as ApiReportDetailResponse } from '../types/api.generated'
import type { BacktestConfig, DatasetInfo, ReportDetail, ReportStatus, ReportSymbol } from '../types/report'

function toRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function toReportStatus(value: string): ReportStatus {
  if (value === 'draft' || value === 'reviewed' || value === 'adopted' || value === 'rejected' || value === 'archived') return value
  return 'submitted'
}

function toMetrics(value: Record<string, unknown>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1])),
  )
}

function toEquityCurve(value: unknown): { date: string; value: number }[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const row = toRecord(item)
    const date = toString(row.date) || toString(row.timestamp)
    const pointValue = typeof row.value === 'number' ? row.value : row.equity
    return date && typeof pointValue === 'number' ? [{ date, value: pointValue }] : []
  })
}

function toBacktestConfig(value: unknown): BacktestConfig | undefined {
  const row = toRecord(value)
  if (Object.keys(row).length === 0) return undefined
  return {
    initial_balance: toNullableNumber(row.initial_balance) ?? undefined,
    timeframe: toString(row.timeframe) || undefined,
    buy_commission_rate: toNullableNumber(row.buy_commission_rate) ?? undefined,
    sell_commission_rate: toNullableNumber(row.sell_commission_rate) ?? undefined,
    slippage_rate: toNullableNumber(row.slippage_rate) ?? undefined,
  }
}

function toDatasetInfo(value: unknown): DatasetInfo {
  const row = toRecord(value)
  return {
    symbol: toString(row.symbol),
    symbol_name: toString(row.symbol_name) || undefined,
    timeframe: toString(row.timeframe) || undefined,
    start_date: toString(row.start_date) || undefined,
    end_date: toString(row.end_date) || undefined,
  }
}

function toReportSymbol(value: string | Record<string, unknown>): ReportSymbol {
  if (typeof value === 'string') {
    return { symbol: value, name: value, timeframe: '', period: '', rows: 0 }
  }
  return {
    symbol: toString(value.symbol),
    name: toString(value.name) || toString(value.symbol),
    timeframe: toString(value.timeframe),
    period: toString(value.period),
    rows: toNumber(value.rows),
  }
}

function toReportDetail(raw: ApiReportDetailResponse): ReportDetail {
  return {
    report_id: raw.report_id,
    strategy_name: raw.strategy_name,
    strategy_version: raw.strategy_version,
    strategy_path: raw.strategy_path,
    status: toReportStatus(raw.status),
    submitted_at: raw.submitted_at,
    submitted_by: raw.submitted_by,
    submitted_by_id: undefined,
    backtest_period: raw.backtest_period ?? '',
    total_return_pct: raw.total_return_pct ?? 0,
    total_trades: raw.total_trades ?? 0,
    sharpe_ratio: raw.sharpe_ratio ?? null,
    max_drawdown_pct: raw.max_drawdown_pct ?? null,
    win_rate: raw.win_rate ?? null,
    summary: raw.summary,
    rationale: raw.rationale,
    risks: raw.risks,
    recommendations: raw.recommendations,
    equity_curve: toEquityCurve(raw.equity_curve),
    metrics: toMetrics(raw.metrics),
    initial_balance: raw.initial_balance ?? null,
    final_balance: raw.final_balance ?? null,
    symbols: raw.symbols.map(toReportSymbol),
    user_notes: raw.user_notes,
    reviewed_at: raw.reviewed_at ?? null,
    config: toBacktestConfig(raw.config),
    datasets: raw.datasets.map(toDatasetInfo),
  }
}

export async function getReportDetail(id: string): Promise<ReportDetail> {
  const res = await client.get<ApiReportDetailResponse>(`/api/reports/${id}`)
  return toReportDetail(res.data)
}
