/**
 * System 도메인 타입.
 *
 * 전역 거래 상태는 SSOT가 아니다. 시스템 정지/재개 상태는
 * `useAccounts()`로 받아온 계좌별 status (active/suspended) 집계로 계산한다.
 * SSOT: `docs/specs/account/02-design-decisions.md`.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export interface SystemStatus {
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
