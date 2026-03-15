import client from './client'
import type { PortfolioValue, PortfolioHistoryPoint, Period } from '../types/portfolio'

export async function getPortfolioValue(): Promise<PortfolioValue> {
  const res = await client.get('/api/portfolio/value')
  return res.data
}

export async function getPortfolioHistory(period: Period): Promise<PortfolioHistoryPoint[]> {
  const res = await client.get('/api/portfolio/history', { params: { period } })
  return res.data
}
