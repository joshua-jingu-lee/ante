import client from './client'
import type {
  BotBudgetView,
  TreasurySummaryView,
  TreasuryTransactionView,
  TreasurySnapshotView,
} from '../types/treasury'
import type {
  BudgetChangeRequest,
  BudgetItem,
  BudgetListResponse,
  BudgetOperationResponse,
  SnapshotItem,
  SnapshotListResponse,
  TransactionItem,
  TransactionListResponse,
  TreasurySummaryResponse,
} from '../types/api.generated'

type ExtraRecord = Record<string, unknown>

function extra(raw: object): ExtraRecord {
  return raw as ExtraRecord
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' ? value : fallback
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function toTreasurySummaryView(raw: TreasurySummaryResponse): TreasurySummaryView {
  const e = extra(raw)
  return {
    total_allocated: raw.total_allocated,
    total_balance: raw.total_balance,
    total_evaluation: raw.total_evaluation,
    total_profit_loss: raw.total_profit_loss,
    unallocated: raw.unallocated,
    commission_rate: raw.commission_rate,
    sell_tax_rate: raw.sell_tax_rate,
    broker_id: raw.broker_id ?? undefined,
    broker_name: raw.broker_name ?? undefined,
    broker_short_name: raw.broker_short_name ?? undefined,
    exchange: raw.exchange ?? undefined,
    account_no: raw.account_no ?? undefined,
    is_virtual: raw.is_virtual ?? undefined,
    synced_at: raw.synced_at ?? undefined,
    account_balance: numberValue(e.account_balance, raw.total_balance),
    purchasable_amount: numberValue(e.purchasable_amount),
    account_number: optionalString(e.account_number) ?? raw.account_no ?? undefined,
    is_demo_trading: optionalBoolean(e.is_demo_trading),
    last_sync_time: optionalString(e.last_sync_time) ?? raw.synced_at ?? undefined,
    total_reserved: numberValue(e.total_reserved),
    total_available: numberValue(e.total_available, raw.unallocated),
    bot_count: numberValue(e.bot_count),
    ante_purchase_amount: numberValue(e.ante_purchase_amount),
    ante_eval_amount: numberValue(e.ante_eval_amount),
    ante_profit_loss: numberValue(e.ante_profit_loss),
    budget_exceeds_purchasable: optionalBoolean(e.budget_exceeds_purchasable),
  }
}

function toBotBudgetView(raw: BudgetItem): BotBudgetView {
  const e = extra(raw)
  return {
    bot_id: raw.bot_id,
    allocated: raw.allocated,
    available: raw.available,
    reserved: raw.reserved,
    spent: raw.spent,
    returned: raw.returned,
    eval_amount: numberValue(e.eval_amount),
    position_pnl: numberValue(e.position_pnl),
    position_return: numberValue(e.position_return),
  }
}

function toTreasurySnapshotView(raw: SnapshotItem): TreasurySnapshotView {
  return {
    account_id: raw.account_id,
    snapshot_date: raw.snapshot_date,
    total_asset: raw.total_asset,
    ante_eval_amount: raw.ante_eval_amount,
    ante_purchase_amount: raw.ante_purchase_amount,
    unallocated: raw.unallocated,
    account_balance: raw.account_balance,
    total_allocated: raw.total_allocated,
    bot_count: raw.bot_count,
    daily_pnl: raw.daily_pnl,
    daily_return: raw.daily_return,
    net_trade_amount: raw.net_trade_amount,
    unrealized_pnl: raw.unrealized_pnl,
    created_at: raw.created_at,
  }
}

function toTreasuryTransactionView(raw: TransactionItem): TreasuryTransactionView {
  return {
    id: raw.id,
    type: raw.type,
    bot_id: raw.bot_id ?? undefined,
    amount: raw.amount,
    description: raw.description,
    created_at: raw.created_at,
  }
}

export async function getTreasurySummary(): Promise<TreasurySummaryView> {
  const res = await client.get<TreasurySummaryResponse>('/api/treasury')
  return toTreasurySummaryView(res.data)
}

export async function getTreasurySnapshots(params: {
  account_id?: string
  start_date?: string
  end_date?: string
}): Promise<TreasurySnapshotView[]> {
  const res = await client.get<SnapshotListResponse>('/api/treasury/snapshots', { params })
  return res.data.snapshots.map(toTreasurySnapshotView)
}

export async function getBotBudgets(): Promise<BotBudgetView[]> {
  const res = await client.get<BudgetListResponse>('/api/treasury/budgets')
  return res.data.budgets.map(toBotBudgetView)
}

export async function allocateBudget(botId: string, amount: number): Promise<void> {
  const body: BudgetChangeRequest = { amount }
  await client.post<BudgetOperationResponse>(`/api/treasury/bots/${botId}/allocate`, body)
}

export async function deallocateBudget(botId: string, amount: number): Promise<void> {
  const body: BudgetChangeRequest = { amount }
  await client.post<BudgetOperationResponse>(`/api/treasury/bots/${botId}/deallocate`, body)
}

export async function getTreasuryTransactions(params: {
  offset?: number
  limit?: number
  type?: string
  bot_id?: string
  start_date?: string
  end_date?: string
}): Promise<{ items: TreasuryTransactionView[]; total: number }> {
  const res = await client.get<TransactionListResponse>('/api/treasury/transactions', { params })
  return {
    items: res.data.items.map(toTreasuryTransactionView),
    total: res.data.total,
  }
}
