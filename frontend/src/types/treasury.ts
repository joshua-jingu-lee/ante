export interface TreasurySummary {
  // KIS 계좌
  account_balance: number
  purchasable_amount: number
  total_evaluation: number
  total_profit_loss: number
  commission_rate: number
  sell_tax_rate: number
  // KIS 계좌 헤더
  account_number: string
  is_demo_trading: boolean
  last_sync_time: string | null
  // Ante 관리자산
  total_allocated: number
  total_reserved: number
  total_available: number
  unallocated: number
  bot_count: number
  ante_purchase_amount: number
  ante_eval_amount: number
  ante_profit_loss: number
  budget_exceeds_purchasable: boolean
}

export interface BotBudget {
  bot_id: string
  allocated: number
  available: number
  reserved: number
  spent: number
  returned: number
}

export type TransactionType = 'allocate' | 'deallocate' | 'fill' | 'bot_stopped_release'

export interface TreasuryTransaction {
  id: number
  type: TransactionType
  bot_id?: string
  amount: number
  description: string
  created_at: string
}
