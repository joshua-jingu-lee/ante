export type BotStatus = 'created' | 'running' | 'stopping' | 'stopped' | 'error' | 'deleted'
export type BotMode = 'live' | 'paper'

export interface Bot {
  bot_id: string
  name: string
  strategy_name?: string
  status: BotStatus
  mode: BotMode
  created_at: string
}

export interface BotStrategy {
  name: string
  version: string
  author: string
  description: string
}

export interface BotDetail extends Bot {
  interval_seconds: number
  symbols: string[]
  allocated_budget: number
  logs: BotLog[]
  strategy?: BotStrategy
}

export interface BotLog {
  timestamp: string
  success: boolean
  message?: string
}

export interface BotCreateRequest {
  bot_id: string
  name: string
  strategy_name: string
  mode: BotMode
  interval_seconds: number
  budget: number
  symbols: string[]
}
