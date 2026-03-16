import client from './client'
import type { Strategy, StrategyDetail, StrategyPerformance, Trade, DailySummary, MonthlySummary } from '../types/strategy'

export async function getStrategies(): Promise<Strategy[]> {
  const res = await client.get('/api/strategies')
  return res.data
}

export async function getStrategyDetail(id: number): Promise<StrategyDetail> {
  const res = await client.get(`/api/strategies/${id}`)
  return res.data
}

export async function getStrategyPerformance(id: number): Promise<StrategyPerformance> {
  const res = await client.get(`/api/strategies/${id}/performance`)
  return res.data
}

export async function getStrategyTrades(
  id: number,
  params?: { cursor?: number; limit?: number },
): Promise<{ items: Trade[]; next_cursor?: number }> {
  const res = await client.get(`/api/strategies/${id}/trades`, { params })
  return res.data
}

export async function getStrategyDailySummary(id: number): Promise<DailySummary[]> {
  const res = await client.get(`/api/strategies/${id}/daily-summary`)
  return res.data.items
}

export async function getStrategyMonthlySummary(id: number): Promise<MonthlySummary[]> {
  const res = await client.get(`/api/strategies/${id}/monthly-summary`)
  return res.data.items
}
