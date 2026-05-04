/**
 * Portfolio 도메인 타입.
 *
 * `api.generated.ts`의 Portfolio raw contract를
 * `frontend/src/api/portfolio.ts` adapter가 UI/domain model로 변환한다.
 */

export interface PortfolioValueView {
  total_value: number
  daily_pnl: number
  daily_return: number
  unrealized_pnl: number
  updated_at: string
  snapshot_date?: string | null
}

export type PortfolioValue = PortfolioValueView

export interface PortfolioHistoryPointView {
  date: string
  total_asset: number
  daily_pnl: number
  daily_return: number
  unrealized_pnl: number
}

export type PortfolioHistoryPoint = PortfolioHistoryPointView

export interface PortfolioHistoryView {
  data: PortfolioHistoryPointView[]
  start_date: string
  end_date: string
}

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type Period = '1d' | '1w' | '1m' | '3m' | 'all'
