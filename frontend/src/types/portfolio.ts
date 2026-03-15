export interface PortfolioValue {
  total_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  daily_pnl: number
  daily_pnl_pct: number
}

export interface PortfolioHistoryPoint {
  date: string
  value: number
}

export type Period = '1d' | '1w' | '1m' | '3m' | 'all'
