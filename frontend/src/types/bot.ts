/**
 * Bot 도메인 타입.
 *
 * `api.generated.ts`의 BotInfo raw contract를
 * `frontend/src/api/bots.ts` adapter가 UI/domain model로 변환한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type BotStatus = 'created' | 'running' | 'stopping' | 'stopped' | 'error' | 'deleted'
export type BotTradingMode = 'virtual' | 'live'

export interface BotView {
  bot_id: string
  name: string
  strategy_name?: string
  status: BotStatus
  trading_mode: BotTradingMode
  interval_seconds?: number
  created_at: string
}

export type Bot = BotView

export interface BotConfig {
  interval_seconds: number
  auto_restart: boolean
  max_restart_attempts: number
  restart_cooldown_seconds: number
  step_timeout_seconds: number
  max_signals_per_step: number
}

export interface BotStrategy {
  name: string
  version: string
  author_name: string
  author_id: string
  description: string
}

export interface BotBudgetDetail {
  allocated: number
  spent: number
  reserved: number
  available: number
}

export interface BotPosition {
  symbol: string
  quantity: number
  avg_entry_price: number
  current_price?: number
  realized_pnl: number
}

export interface BotDetailView extends BotView {
  interval_seconds: number
  symbols: string[]
  allocated_budget: number
  logs: BotLog[]
  strategy?: BotStrategy
  strategy_author_name?: string
  strategy_author_id?: string
  config?: BotConfig
  budget?: BotBudgetDetail
  positions?: BotPosition[]
}

export type BotDetail = BotDetailView

export type BotLogResult = 'success' | 'failure' | 'stopped'

export interface BotLog {
  timestamp: string
  success: boolean
  result?: BotLogResult
  message?: string
}

export interface BotCreateInput {
  bot_id: string
  name?: string
  strategy_id?: string
  strategy_name?: string
  account_id?: string
  interval_seconds?: number
  budget?: number
}

export interface BotUpdateInput {
  name?: string
  strategy_name?: string
  interval_seconds?: number
  budget?: number
  auto_restart?: boolean
  max_restart_attempts?: number
  restart_cooldown_seconds?: number
  step_timeout_seconds?: number
  max_signals_per_step?: number
}

export type HandlePositions = 'keep' | 'liquidate'
