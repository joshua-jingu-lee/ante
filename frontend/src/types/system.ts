/**
 * System 도메인 타입.
 *
 * generated StatusResponse는 trading_status를 string | null로 선언하므로
 * 프론트엔드에서 유니온 리터럴로 명시한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
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
