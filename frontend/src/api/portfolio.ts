import client from './client'
import type {
  PortfolioHistoryPointView,
  PortfolioValueView,
  Period,
} from '../types/portfolio'
import type {
  PortfolioHistoryPoint,
  PortfolioHistoryResponse,
  PortfolioValueResponse,
} from '../types/api.generated'

function toPortfolioValueView(raw: PortfolioValueResponse): PortfolioValueView {
  return {
    total_value: raw.total_value,
    daily_pnl: raw.daily_pnl,
    daily_return: raw.daily_return,
    unrealized_pnl: raw.unrealized_pnl,
    updated_at: raw.updated_at,
    snapshot_date: raw.snapshot_date,
  }
}

function toPortfolioHistoryPointView(raw: PortfolioHistoryPoint): PortfolioHistoryPointView {
  return {
    date: raw.date,
    total_asset: raw.total_asset,
    daily_pnl: raw.daily_pnl,
    daily_return: raw.daily_return,
    unrealized_pnl: raw.unrealized_pnl,
  }
}

export async function getPortfolioValue(): Promise<PortfolioValueView> {
  const res = await client.get<PortfolioValueResponse>('/api/portfolio/value')
  return toPortfolioValueView(res.data)
}

export async function getPortfolioHistory(period: Period): Promise<PortfolioHistoryPointView[]> {
  const res = await client.get<PortfolioHistoryResponse>('/api/portfolio/history', { params: { period } })
  return res.data.data.map(toPortfolioHistoryPointView)
}
