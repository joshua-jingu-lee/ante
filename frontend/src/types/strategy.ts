export type StrategyStatus = 'registered' | 'active' | 'inactive' | 'archived'

export interface Strategy {
  id: number
  name: string
  version: string
  status: StrategyStatus
  author?: string
  author_id?: string
  bot_id?: string
  cumulative_return?: number
  created_at: string
}

export interface StrategyDetail extends Strategy {
  description?: string
  rationale?: string
  risks?: string
  params?: Record<string, StrategyParam | unknown>
}

export interface StrategyParam {
  value: unknown
  description?: string
}

export interface WeeklySummary {
  week_label: string
  realized_pnl: number
  trade_count: number
  win_rate: number
}

export interface StrategyPerformance {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  total_commission: number
  net_pnl: number
  avg_profit: number
  avg_loss: number
  profit_factor: number
  max_drawdown: number
  max_drawdown_amount: number
  sharpe_ratio: number | null
  active_days: number
  realized_pnl: number
  equity_curve: { date: string; value: number }[]
}

export interface DailySummary {
  date: string
  realized_pnl: number
  trade_count: number
  win_rate: number
}

export interface MonthlySummary {
  year: number
  month: number
  realized_pnl: number
  trade_count: number
  win_rate: number
}

export interface Trade {
  id: number
  strategy_id: number
  bot_id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  executed_at: string
  pnl?: number
}
