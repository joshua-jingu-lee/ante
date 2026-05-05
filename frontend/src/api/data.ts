import client from './client'
import type {
  DatasetDetailResponse as ApiDatasetDetailResponse,
  DatasetItem as ApiDatasetItem,
  DatasetListResponse as ApiDatasetListResponse,
  FeedStatusResponse as ApiFeedStatusResponse,
  OkResponse as ApiOkResponse,
  StorageSummaryResponse as ApiStorageSummaryResponse,
} from '../types/api.generated'
import type { FeedStatus } from '../types/feed'
import type { DataType, Dataset, StorageInfo } from '../types/data'

export type { DataType, Dataset, StorageInfo }

function toRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function toDataType(value: string): DataType {
  return value === 'fundamental' ? 'fundamental' : 'ohlcv'
}

function toDataset(raw: ApiDatasetItem): Dataset {
  return {
    id: raw.id,
    symbol: raw.symbol,
    timeframe: raw.timeframe,
    data_type: toDataType(raw.data_type),
    start_date: raw.start_date ?? '',
    end_date: raw.end_date ?? '',
    row_count: raw.row_count,
    file_size: raw.file_size,
  }
}

function toFeedStatus(raw: ApiFeedStatusResponse): FeedStatus {
  return {
    initialized: raw.initialized,
    checkpoints: raw.checkpoints.map((item) => {
      const row = toRecord(item)
      return {
        source: toString(row.source),
        data_type: toString(row.data_type),
        last_date: toString(row.last_date),
        updated_at: toString(row.updated_at),
      }
    }),
    recent_reports: raw.recent_reports.map((item) => {
      const row = toRecord(item)
      const summary = toRecord(row.summary)
      return {
        mode: toString(row.mode),
        started_at: toString(row.started_at),
        finished_at: toString(row.finished_at),
        duration_seconds: toNumber(row.duration_seconds),
        target_date: toString(row.target_date),
        summary: {
          symbols_total: toNumber(summary.symbols_total),
          symbols_success: toNumber(summary.symbols_success),
          symbols_failed: toNumber(summary.symbols_failed),
          rows_written: toNumber(summary.rows_written),
          data_types: toStringArray(summary.data_types),
        },
        failures: Array.isArray(row.failures)
          ? row.failures.map((failure) => {
            const failureRow = toRecord(failure)
            return {
              symbol: toString(failureRow.symbol),
              date: toString(failureRow.date),
              source: toString(failureRow.source),
              reason: toString(failureRow.reason),
              retries: toNumber(failureRow.retries),
            }
          })
          : [],
        warnings: Array.isArray(row.warnings)
          ? row.warnings.map((warning) => {
            const warningRow = toRecord(warning)
            return {
              symbol: toString(warningRow.symbol),
              date: toString(warningRow.date),
              type: toString(warningRow.type),
              message: toString(warningRow.message),
            }
          })
          : [],
        config_errors: toStringArray(row.config_errors),
      }
    }),
    api_keys: raw.api_keys.map((item) => {
      const row = toRecord(item)
      return {
        key: toString(row.key),
        set: row.set === true,
        source: toString(row.source),
      }
    }),
  }
}

export async function getDatasets(params?: {
  symbol?: string
  timeframe?: string
  data_type?: DataType
  offset?: number
  limit?: number
}): Promise<{ items: Dataset[]; total: number }> {
  const res = await client.get<ApiDatasetListResponse>('/api/data/datasets', { params })
  return {
    items: res.data.items.map(toDataset),
    total: res.data.total,
  }
}

export async function getDatasetDetail(id: string): Promise<{ dataset: Dataset; preview: Record<string, unknown>[] }> {
  const res = await client.get<ApiDatasetDetailResponse>(`/api/data/datasets/${id}`)
  return {
    dataset: toDataset(res.data.dataset),
    preview: res.data.preview,
  }
}

export async function getStorageInfo(): Promise<StorageInfo> {
  const res = await client.get<ApiStorageSummaryResponse>('/api/data/storage')
  return {
    total_bytes: res.data.total_bytes,
    total_mb: res.data.total_mb,
    by_timeframe: res.data.by_timeframe,
    by_data_type: res.data.by_data_type ?? undefined,
  }
}

export async function deleteDataset(id: string, data_type?: DataType): Promise<void> {
  await client.delete<ApiOkResponse>(`/api/data/datasets/${id}`, { params: { data_type } })
}

export async function getFeedStatus(): Promise<FeedStatus> {
  const res = await client.get<ApiFeedStatusResponse>('/api/data/feed-status')
  return toFeedStatus(res.data)
}
