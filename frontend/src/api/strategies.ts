import client from './client'
import type { Strategy, StrategyDetail, StrategyPerformance, Trade, DailySummary, MonthlySummary } from '../types/strategy'

export async function getStrategies(): Promise<Strategy[]> {
  const res = await client.get('/api/strategies')
  return res.data.strategies ?? res.data
}

export async function getStrategyDetail(id: string): Promise<StrategyDetail> {
  const res = await client.get(`/api/strategies/${id}`)
  return res.data.strategy ?? res.data
}

export async function getStrategyPerformance(id: string): Promise<StrategyPerformance> {
  const res = await client.get(`/api/strategies/${id}/performance`)
  return res.data
}

export async function getStrategyTrades(
  id: string,
  params?: { cursor?: number; limit?: number },
): Promise<{ items: Trade[]; next_cursor?: number }> {
  const res = await client.get(`/api/strategies/${id}/trades`, { params })
  return { items: res.data.trades ?? [], next_cursor: res.data.next_cursor }
}

export async function getStrategyDailySummary(id: string): Promise<DailySummary[]> {
  const res = await client.get(`/api/strategies/${id}/daily-summary`)
  return res.data.items
}

export async function getStrategyMonthlySummary(id: string): Promise<MonthlySummary[]> {
  const res = await client.get(`/api/strategies/${id}/monthly-summary`)
  return res.data.items
}
