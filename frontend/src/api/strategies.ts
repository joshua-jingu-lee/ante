import client from './client'
import type { Strategy, StrategyDetail, StrategyPerformance, Trade } from '../types/strategy'

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
