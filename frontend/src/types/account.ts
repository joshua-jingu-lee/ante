/**
 * Account 도메인 타입.
 *
 * `api.generated.ts`의 AccountResponse raw contract를
 * `frontend/src/api/accounts.ts` adapter가 UI/domain model로 변환한다.
 */

export type AccountStatus = 'active' | 'suspended' | 'deleted' | (string & {})

export interface AccountView {
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

export type Account = AccountView
