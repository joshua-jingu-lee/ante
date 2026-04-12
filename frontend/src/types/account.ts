/**
 * Account 도메인 타입.
 *
 * 백엔드 AccountResponse 스키마 기반.
 * api.generated.ts에 Account 타입이 아직 없으므로 프론트엔드에서 명시 정의한다.
 */

export type AccountStatus = 'active' | 'suspended' | 'deleted'

export interface Account {
  account_id: string
  name: string
  exchange: string
  currency: string
  timezone: string
  trading_hours_start: string
  trading_hours_end: string
  trading_mode: string
  broker_type: string
  broker_config: Record<string, unknown>
  buy_commission_rate: number
  sell_commission_rate: number
  status: AccountStatus
  created_at: string
  updated_at: string
}
