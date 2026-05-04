import client from './client'
import type { AccountView, AccountStatus } from '../types/account'
import type { AccountListResponse, AccountResponse } from '../types/api.generated'

function toAccountStatus(status: string): AccountStatus {
  return status
}

function toAccountView(raw: AccountResponse): AccountView {
  return {
    account_id: raw.account_id,
    name: raw.name,
    exchange: raw.exchange,
    currency: raw.currency,
    timezone: raw.timezone,
    trading_hours_start: raw.trading_hours_start,
    trading_hours_end: raw.trading_hours_end,
    trading_mode: raw.trading_mode,
    broker_type: raw.broker_type,
    broker_config: raw.broker_config,
    buy_commission_rate: raw.buy_commission_rate,
    sell_commission_rate: raw.sell_commission_rate,
    status: toAccountStatus(raw.status),
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  }
}

export async function getAccounts(params?: { status?: string }): Promise<AccountView[]> {
  const res = await client.get<AccountListResponse>('/api/accounts', { params })
  return res.data.accounts.map(toAccountView)
}
