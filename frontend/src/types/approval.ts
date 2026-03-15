export type ApprovalStatus = 'pending' | 'approved' | 'rejected'
export type ApprovalType = 'strategy_report' | 'budget_allocation' | 'live_switch' | 'risk_alert'

export interface Approval {
  id: number
  type: ApprovalType
  title: string
  requester: string
  requested_at: string
  status: ApprovalStatus
  reference_id?: number
  memo?: string
  resolved_at?: string
  resolved_by?: string
}

export interface ApprovalDetail extends Approval {
  detail?: StrategyReportDetail
}

export interface StrategyReportDetail {
  strategy_name: string
  strategy_version: string
  agent_summary: string
  agent_rationale: string
  agent_risks: string
  agent_recommendation: string
  backtest_start: string
  backtest_end: string
  metrics: BacktestMetrics
  equity_curve: { date: string; value: number }[]
  drawdown: { date: string; value: number }[]
}

export interface BacktestMetrics {
  sharpe_ratio: number
  max_drawdown: number
  win_rate: number
  profit_factor: number
  total_trades: number
  total_return: number
  annual_return: number
}
