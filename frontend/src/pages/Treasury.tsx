import { useState, useMemo } from 'react'
import { useTreasurySummary, useBotBudgets, useTreasurySnapshots } from '../hooks/useTreasury'
import VirtualModeBanner from '../components/common/VirtualModeBanner'
import AccountSummary from '../components/treasury/AccountSummary'
import AnteSummary from '../components/treasury/AnteSummary'
import BudgetPieChart from '../components/treasury/BudgetPieChart'
import BudgetTable from '../components/treasury/BudgetTable'
import AllocationForm from '../components/treasury/AllocationForm'
import RecentTransactions from '../components/treasury/RecentTransactions'
import AssetTrendChart from '../components/charts/AssetTrendChart'
import { formatKRW, formatPercent } from '../utils/formatters'
import { PageSkeleton } from '../components/common/Skeleton'

type PeriodKey = '1w' | '1m' | '3m' | '1y' | 'all'

const PERIODS: { key: PeriodKey; label: string; days: number | null }[] = [
  { key: '1w', label: '1주', days: 7 },
  { key: '1m', label: '1개월', days: 30 },
  { key: '3m', label: '3개월', days: 90 },
  { key: '1y', label: '1년', days: 365 },
  { key: 'all', label: '전체', days: null },
]

function getDateRange(period: PeriodKey): { start_date?: string; end_date: string } {
  const today = new Date()
  const end_date = today.toISOString().slice(0, 10)
  const selected = PERIODS.find((p) => p.key === period)
  if (!selected || selected.days === null) {
    return { end_date }
  }
  const start = new Date(today)
  start.setDate(start.getDate() - selected.days)
  return { start_date: start.toISOString().slice(0, 10), end_date }
}

export default function Treasury() {
  const [period, setPeriod] = useState<PeriodKey>('1w')
  const { data: summary, isLoading: summaryLoading } = useTreasurySummary()
  const { data: budgets, isLoading: budgetsLoading } = useBotBudgets()

  const dateRange = useMemo(() => getDateRange(period), [period])
  const { data: snapshots } = useTreasurySnapshots(dateRange)

  if (summaryLoading || budgetsLoading) return <PageSkeleton />

  const isVirtual = summary?.is_virtual === true

  // Period summary calculations
  const periodPnl = (snapshots ?? []).reduce((sum, s) => sum + s.daily_pnl, 0)
  const periodReturn = (snapshots ?? []).reduce((acc, s) => acc * (1 + s.daily_return), 1) - 1
  const periodPnlColor = periodPnl >= 0 ? 'text-positive' : 'text-negative'
  const lastSnapshot = (snapshots ?? []).length > 0 ? (snapshots ?? [])[(snapshots ?? []).length - 1] : null

  return (
    <>
      <VirtualModeBanner isVirtual={isVirtual} />

      {!isVirtual && summary && <AccountSummary summary={summary} />}
      {summary && (
        <AnteSummary summary={summary}>
          {/* T-2: Asset Trend Chart inside Ante card */}
          <div className="border-t border-border px-5 pt-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="font-semibold mb-1">자산 추이</div>
                <div className="text-[13px] text-text-muted">
                  기간 손익 <span className={`font-semibold ${periodPnlColor}`}>{formatKRW(periodPnl)}</span>
                  {' '}&middot;{' '}
                  기간 수익률 <span className={`font-semibold ${periodPnlColor}`}>{formatPercent(periodReturn)}</span>
                </div>
              </div>
              <div className="flex gap-1">
                {PERIODS.map((p) => (
                  <button
                    key={p.key}
                    onClick={() => setPeriod(p.key)}
                    className={`px-3 py-1 rounded text-[12px] font-medium cursor-pointer border-none ${
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
          </div>
          <div className="mx-5 mb-2">
            <AssetTrendChart data={snapshots ?? []} />
          </div>
          {lastSnapshot && (
            <div className="text-right text-[11px] text-text-muted px-5 pb-4">
              산정 기준일 {lastSnapshot.snapshot_date}
            </div>
          )}
        </AnteSummary>
      )}

      <div className="grid grid-cols-[1fr_1fr] gap-6 mb-6">
        {/* 파이 차트 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">Bot 예산 비중</h3>
          <BudgetPieChart budgets={budgets ?? []} />
        </div>

        {/* 예산 관리 폼 */}
        {(budgets ?? []).length > 0 && <AllocationForm budgets={budgets ?? []} />}
      </div>

      <BudgetTable budgets={budgets ?? []} />
      <RecentTransactions />
    </>
  )
}
