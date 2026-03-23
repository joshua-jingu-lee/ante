/**
 * Feed 도메인 타입.
 *
 * generated FeedStatusResponse는 내부 배열을 { [key: string]: unknown }[]로 선언하므로
 * 프론트엔드에서 상세 필드를 명시적으로 정의한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export interface FeedCheckpoint {
  source: string
  data_type: string
  last_date: string
  updated_at: string
}

export interface FeedReportSummary {
  symbols_total: number
  symbols_success: number
  symbols_failed: number
  rows_written: number
  data_types: string[]
}

export interface FeedReport {
  mode: string
  started_at: string
  finished_at: string
  duration_seconds: number
  target_date: string
  summary: FeedReportSummary
  failures: Array<{
    symbol: string
    date: string
    source: string
    reason: string
    retries: number
  }>
  warnings: Array<{
    symbol: string
    date: string
    type: string
    message: string
  }>
  config_errors: string[]
}

export interface FeedApiKeyStatus {
  key: string
  set: boolean
  source: string
}

export interface FeedStatus {
  initialized: boolean
  checkpoints: FeedCheckpoint[]
  recent_reports: FeedReport[]
  api_keys: FeedApiKeyStatus[]
}
