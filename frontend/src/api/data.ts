import client from './client'

export interface Dataset {
  id: number
  symbol: string
  timeframe: string
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

export async function deleteDataset(id: number): Promise<void> {
  await client.delete(`/api/data/datasets/${id}`)
}
