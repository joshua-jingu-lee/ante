import { useState } from 'react'
import { usePortfolioValue, usePortfolioHistory } from '../../hooks/usePortfolio'
import { formatKRW, formatPercent } from '../../utils/formatters'
import type { Period } from '../../types/portfolio'
import LoadingSpinner from '../common/LoadingSpinner'

const PERIODS: { key: Period; label: string }[] = [
  { key: '1d', label: '1일' },
  { key: '1w', label: '1주' },
  { key: '1m', label: '1개월' },
  { key: '3m', label: '3개월' },
  { key: 'all', label: '전체' },
]

export default function PortfolioChart() {
  const [period, setPeriod] = useState<Period>('1w')
  const { data: value, isLoading: valueLoading } = usePortfolioValue()
  const { data: history, isLoading: historyLoading } = usePortfolioHistory(period)

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          {valueLoading ? (
            <div className="h-10 w-48 bg-surface-hover rounded animate-pulse" />
          ) : (
            <>
              <div className="text-[32px] font-bold">{formatKRW(value?.total_value ?? 0)}</div>
              <div className="mt-1">
                <span
                  className={`text-[14px] font-semibold ${
                    (value?.daily_pnl ?? 0) >= 0 ? 'text-positive' : 'text-negative'
                  }`}
                >
                  {(value?.daily_pnl ?? 0) >= 0 ? '+' : ''}
                  {formatKRW(value?.daily_pnl ?? 0)} ({formatPercent((value?.daily_pnl_pct ?? 0) / 100)})
                </span>
                <span className="text-text-muted text-[12px] ml-2">오늘</span>
              </div>
            </>
          )}
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-3 py-1 rounded text-[12px] font-medium border-none cursor-pointer ${
                period === p.key
                  ? 'bg-primary text-white'
                  : 'bg-transparent text-text-muted hover:text-text'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {historyLoading ? (
        <LoadingSpinner />
      ) : history && history.length > 0 ? (
        <div className="h-[280px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
          📈 자산 추이 차트 (TradingView Area Chart) — {history.length}개 데이터 포인트
        </div>
      ) : (
        <div className="h-[280px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
          📈 자산 추이 차트 (TradingView Area Chart)
        </div>
      )}
    </div>
  )
}
