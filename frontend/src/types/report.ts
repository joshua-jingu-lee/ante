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
