export type StrategyStatus = 'registered' | 'active' | 'inactive' | 'archived'

export interface Strategy {
  id: number
  name: string
  version: string
  status: StrategyStatus
  author?: string
  bot_id?: string
  cumulative_return?: number
  created_at: string
}

export interface StrategyDetail extends Strategy {
  description?: string
  params?: Record<string, unknown>
}

export interface StrategyPerformance {
  total_trades: number
  win_rate: number
  profit_factor: number
  max_drawdown: number
  realized_pnl: number
  sharpe_ratio: number
  equity_curve: { date: string; value: number }[]
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
