/**
 * Bot 도메인 타입.
 *
 * API 응답 타입은 api.generated.ts에서 자동 생성된 타입을 사용한다.
 * 백엔드가 dict 기반(extra="allow") 응답을 반환하므로 상세 필드를 프론트엔드에서 명시한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type BotStatus = 'created' | 'running' | 'stopping' | 'stopped' | 'error' | 'deleted'
export type BotMode = 'live' | 'paper'

export interface Bot {
  bot_id: string
  name: string
  strategy_name?: string
  status: BotStatus
  mode: BotMode
  interval_seconds?: number
  created_at: string
}

export interface BotStrategy {
  name: string
  version: string
  author: string
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

export interface BotDetail extends Bot {
  interval_seconds: number
  symbols: string[]
  allocated_budget: number
  logs: BotLog[]
  strategy?: BotStrategy
  budget?: BotBudgetDetail
  positions?: BotPosition[]
}

export type BotLogResult = 'success' | 'failure' | 'stopped'

export interface BotLog {
  timestamp: string
  success: boolean
  result?: BotLogResult
  message?: string
}

export interface BotCreateRequest {
  bot_id: string
  name: string
  strategy_name: string
  interval_seconds: number
  budget: number
  symbols: string[]
}
