import client from './client'
import type { TreasurySummary, BotBudget, TreasuryTransaction } from '../types/treasury'

export async function getTreasurySummary(): Promise<TreasurySummary> {
  const res = await client.get('/api/treasury')
  return res.data
}

export async function getBotBudgets(): Promise<BotBudget[]> {
  const res = await client.get('/api/treasury/budgets')
  return res.data
}

export async function allocateBudget(botId: string, amount: number): Promise<void> {
  await client.post(`/api/treasury/bots/${botId}/allocate`, { amount })
}

export async function deallocateBudget(botId: string, amount: number): Promise<void> {
  await client.post(`/api/treasury/bots/${botId}/deallocate`, { amount })
}

export async function getTreasuryHistory(params: {
  offset?: number
  limit?: number
}): Promise<{ items: TreasuryTransaction[]; total: number }> {
  const res = await client.get('/api/audit', { params: { ...params, category: 'treasury' } })
  return res.data
}
