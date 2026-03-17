export interface SystemStatus {
  trading_status: 'ACTIVE' | 'HALTED'
  uptime_seconds: number
  running_bots: number
  version: string
  halt_time?: string
  halt_reason?: string
}

export interface BrokerStatus {
  connected: boolean
  mode: 'live' | 'paper'
  token_expires_at?: string
}

export interface DynamicConfig {
  key: string
  value: string
  description?: string
}
