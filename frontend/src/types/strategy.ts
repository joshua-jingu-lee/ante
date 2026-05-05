/**
 * Strategy 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/strategies.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
 */

export interface EquityCurvePoint {
  date: string
  value: number
}

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type StrategyStatus = 'registered' | 'adopted' | 'active' | 'inactive' | 'archived'

/**
 * 전략 목록 아이템.
 * generated StrategyListItem + 프론트엔드에서 사용하는 추가 필드.
 */
export interface Strategy {
  id: string | number
  name: string
  version: string
  status: string
  author_name: string
  author_id: string
  bot_id?: string | null
  bot_status?: string | null
  cumulative_return?: number
  backtest_return?: number | null
  budget_allocated?: number
  created_at?: string
}

/** 전략 상세 — 백엔드가 dict 기반 응답을 반환하므로 프론트엔드에서 명시 */
export interface StrategyDetail extends Strategy {
  description?: string
  rationale?: string
  risks?: string | string[]
  params?: Record<string, StrategyParam | unknown>
  param_schema?: Record<string, string>
  budget_allocated?: number
  unrealized_pnl?: number
}

export interface StrategyParam {
  value: unknown
  description?: string
}

/**
 * 전략 성과.
 * generated StrategyPerformanceResponse에 index signature가 있어
 * 모든 필드가 unknown이 되므로 프론트엔드에서 명시적으로 정의한다.
 */
export interface StrategyPerformance {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  total_commission?: number
  net_pnl?: number
  avg_profit?: number
  avg_loss?: number
  avg_pnl?: number
  profit_factor: number
  max_drawdown: number
  max_drawdown_amount?: number
  sharpe_ratio: number | null
  active_days?: number
  realized_pnl?: number
  unrealized_pnl?: number
  budget_allocated?: number
  equity_curve: EquityCurvePoint[]
}

/**
 * 거래 내역.
 * generated StrategyTradeItem과 필드명이 다르므로 프론트엔드에서 명시.
 */
export interface Trade {
  id?: string | number
  trade_id?: string
  strategy_id?: number
  bot_id: string
  symbol: string
  symbol_name?: string
  side: string
  quantity: number
  price: number
  executed_at?: string
  timestamp?: string
  status?: string
  pnl?: number
  commission?: number
}

export interface DailySummary {
  date: string
  realized_pnl: number
  trade_count: number
  win_rate: number
}

export interface WeeklySummary {
  week_start: string
  week_end: string
  week_label: string
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
