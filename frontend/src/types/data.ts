export type DataType = 'ohlcv' | 'fundamental'

export interface Dataset {
  id: string
  symbol: string
  timeframe: string
  data_type: DataType
  start_date: string
  end_date: string
  row_count: number
  file_size?: number
}

export interface StorageInfo {
  total_bytes: number
  total_mb: number
  by_timeframe: Record<string, number>
}
