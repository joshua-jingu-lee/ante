import client from './client'
import type { FeedStatus } from '../types/feed'

export type DataType = 'ohlcv' | 'fundamental'

export interface Dataset {
  id: number
  symbol: string
  timeframe: string
  data_type: DataType
  start_date: string
  end_date: string
  row_count: number
}

export interface StorageInfo {
  total_bytes: number
  total_mb: number
  by_timeframe: Record<string, number>
}

export async function getDatasets(params?: {
  symbol?: string
  timeframe?: string
  data_type?: DataType
  offset?: number
  limit?: number
}): Promise<{ items: Dataset[]; total: number }> {
  const res = await client.get('/api/data/datasets', { params })
  return res.data
}

export async function getStorageInfo(): Promise<StorageInfo> {
  const res = await client.get('/api/data/storage')
  return res.data
}

export async function deleteDataset(id: number, data_type?: DataType): Promise<void> {
  await client.delete(`/api/data/datasets/${id}`, { params: { data_type } })
}

export async function getFeedStatus(): Promise<FeedStatus> {
  const res = await client.get('/api/data/feed-status')
  return res.data
}
