/**
 * Report 도메인 타입.
 *
 * api.generated.ts의 ReportDetailResponse가 일부 필드를 unknown[]으로 반환하므로
 * 프론트엔드에서 상세 필드를 명시적으로 정의한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type ReportStatus = 'draft' | 'submitted' | 'reviewed' | 'adopted' | 'rejected' | 'archived'

export interface ReportSymbol {
  symbol: string
  name: string
  timeframe: string
  period: string
  rows: number
}

export interface ReportDetail {
  report_id: string
  strategy_name: string
  strategy_version: string
  strategy_path: string
  status: ReportStatus
  submitted_at: string
  submitted_by: string
  backtest_period: string
  total_return_pct: number
  total_trades: number
  sharpe_ratio: number | null
  max_drawdown_pct: number | null
  win_rate: number | null
  summary: string
  rationale: string
  risks: string
  recommendations: string
  equity_curve: { date: string; value: number }[]
  metrics: Record<string, number>
  initial_balance: number | null
  final_balance: number | null
  symbols: ReportSymbol[]
  user_notes: string
  reviewed_at: string | null
}
