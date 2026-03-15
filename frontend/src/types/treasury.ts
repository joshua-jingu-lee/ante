export interface TreasurySummary {
  total_balance: number
  allocated: number
  unallocated: number
  reserved: number
}

export interface BotBudget {
  bot_id: string
  allocated: number
  available: number
  reserved: number
  used: number
}

export interface TreasuryTransaction {
  id: number
  type: 'allocate' | 'deallocate' | 'trade' | 'deposit' | 'withdrawal'
  bot_id?: string
  amount: number
  description: string
  created_at: string
}
