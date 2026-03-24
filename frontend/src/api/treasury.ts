import client from './client'
import type { TreasurySummary, BotBudget, TreasuryTransaction, TreasurySnapshot } from '../types/treasury'

export async function getTreasurySummary(): Promise<TreasurySummary> {
  const res = await client.get('/api/treasury')
  return res.data
}

export async function getTreasurySnapshots(params: {
  account_id?: string
  start_date?: string
  end_date?: string
}): Promise<TreasurySnapshot[]> {
  const res = await client.get('/api/treasury/snapshots', { params })
  return res.data.snapshots ?? []
}

export async function getBotBudgets(): Promise<BotBudget[]> {
  const res = await client.get('/api/treasury/budgets')
  return res.data.budgets ?? res.data
}

export async function allocateBudget(botId: string, amount: number): Promise<void> {
  await client.post(`/api/treasury/bots/${botId}/allocate`, { amount })
}

export async function deallocateBudget(botId: string, amount: number): Promise<void> {
  await client.post(`/api/treasury/bots/${botId}/deallocate`, { amount })
}

export async function getTreasuryTransactions(params: {
  offset?: number
  limit?: number
  type?: string
  bot_id?: string
  start_date?: string
  end_date?: string
}): Promise<{ items: TreasuryTransaction[]; total: number }> {
  const res = await client.get('/api/treasury/transactions', { params })
  return res.data
}
