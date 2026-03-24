import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useStrategies, useStrategyPerformance, useStrategyDailySummary, useStrategyWeeklySummary, useStrategyMonthlySummary } from '../hooks/useStrategies'
import { PageSkeleton } from '../components/common/Skeleton'
import Pagination from '../components/common/Pagination'
import { formatKRW, formatPercent } from '../utils/formatters'
import type { DailySummary, WeeklySummary, MonthlySummary } from '../types/strategy'

type PeriodTab = 'daily' | 'weekly' | 'monthly'

const DAILY_PAGE_SIZE = 20
const WEEKLY_PAGE_SIZE = 20
const MONTHLY_PAGE_SIZE = 20

function StatCard({ label, value, colorClass }: { label: string; value: string; colorClass?: string }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <div className="text-[12px] text-text-muted mb-1">{label}</div>
      <div className={`text-[18px] font-bold ${colorClass ?? ''}`}>{value}</div>
    </div>
  )
}

function DailyTable({ items, offset, startDate, endDate }: { items: DailySummary[]; offset: number; startDate: string; endDate: string }) {
  let filtered = items
  if (startDate) filtered = filtered.filter((d) => d.date >= startDate)
  if (endDate) filtered = filtered.filter((d) => d.date <= endDate)
  const page = filtered.slice(offset, offset + DAILY_PAGE_SIZE)

  if (page.length === 0) {
    return <div className="py-8 text-center text-text-muted text-[13px]">데이터가 없습니다</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">일자</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">거래 수</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">승률</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">실현 손익</th>
          </tr>
        </thead>
        <tbody>
          {page.map((d) => (
            <tr key={d.date} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{d.date}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{d.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(d.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${d.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                {formatKRW(d.realized_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function WeeklyTable({ items, offset, startDate, endDate }: { items: WeeklySummary[]; offset: number; startDate: string; endDate: string }) {
  let filtered = items
  if (startDate) filtered = filtered.filter((w) => w.week_end >= startDate)
  if (endDate) filtered = filtered.filter((w) => w.week_start <= endDate)
  const page = filtered.slice(offset, offset + WEEKLY_PAGE_SIZE)

  if (page.length === 0) {
    return <div className="py-8 text-center text-text-muted text-[13px]">데이터가 없습니다</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">주간</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">거래 수</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">승률</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">실현 손익</th>
          </tr>
        </thead>
        <tbody>
          {page.map((w) => (
            <tr key={w.week_start} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{w.week_start} ~ {w.week_end.slice(5)}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{w.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(w.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${w.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                {formatKRW(w.realized_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MonthlyTable({ items, offset, startDate, endDate }: { items: MonthlySummary[]; offset: number; startDate: string; endDate: string }) {
  let filtered = items
  if (startDate) {
    const [sy, sm] = startDate.split('-').map(Number)
    filtered = filtered.filter((m) => m.year > sy || (m.year === sy && m.month >= sm))
  }
  if (endDate) {
    const [ey, em] = endDate.split('-').map(Number)
    filtered = filtered.filter((m) => m.year < ey || (m.year === ey && m.month <= em))
  }
  const page = filtered.slice(offset, offset + MONTHLY_PAGE_SIZE)

  if (page.length === 0) {
    return <div className="py-8 text-center text-text-muted text-[13px]">데이터가 없습니다</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">월</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">거래 수</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">승률</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">실현 손익</th>
          </tr>
        </thead>
        <tbody>
          {page.map((m) => (
            <tr key={`${m.year}-${m.month}`} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{m.year}-{String(m.month).padStart(2, '0')}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{m.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(m.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${m.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                {formatKRW(m.realized_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Performance() {
  const { id: routeId = '' } = useParams<{ id: string }>()
  const [selectedStrategyId, setSelectedStrategyId] = useState(routeId)
  const [strategySearch, setStrategySearch] = useState('')
  const [tab, setTab] = useState<PeriodTab>('monthly')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [appliedStartDate, setAppliedStartDate] = useState('')
  const [appliedEndDate, setAppliedEndDate] = useState('')
  const [dailyOffset, setDailyOffset] = useState(0)
  const [weeklyOffset, setWeeklyOffset] = useState(0)
  const [monthlyOffset, setMonthlyOffset] = useState(0)

  const strategyId = selectedStrategyId || routeId

  const { data: strategies } = useStrategies()
  const { data: performance, isLoading } = useStrategyPerformance(strategyId)
  const { data: dailyData } = useStrategyDailySummary(strategyId)
  const { data: weeklyData } = useStrategyWeeklySummary(strategyId)
  const { data: monthlyData } = useStrategyMonthlySummary(strategyId)

  if (isLoading && !performance) return <PageSkeleton />

  const daily = (dailyData ?? []).slice().reverse()
  const weekly = (weeklyData ?? []).slice().reverse()
  const monthly = (monthlyData ?? []).slice().reverse()

  const tabConfig: { key: PeriodTab; label: string }[] = [
    { key: 'daily', label: '일별' },
    { key: 'weekly', label: '주별' },
    { key: 'monthly', label: '월별' },
  ]

  const totalPnl = performance?.realized_pnl ?? 0
  const totalTrades = performance?.total_trades ?? 0
  const winRate = performance?.win_rate ?? 0
  const profitFactor = performance?.profit_factor

  const handleQuery = () => {
    setAppliedStartDate(startDate)
    setAppliedEndDate(endDate)
    setDailyOffset(0)
    setWeeklyOffset(0)
    setMonthlyOffset(0)
  }

  const handleStrategySelect = (value: string) => {
    setStrategySearch(value)
    // find matching strategy by name
    const match = (strategies ?? []).find((s) => s.name === value)
    if (match) {
      setSelectedStrategyId(String(match.id))
    }
  }

  return (
    <>
      {/* 헤더 */}
      <div className="flex items-center gap-3 mb-6">
        <Link
          to={`/strategies/${strategyId}`}
          className="text-[13px] text-text-muted no-underline hover:text-text"
        >
          &larr; 전략 상세
        </Link>
        <h2 className="text-[18px] font-bold">기간별 성과</h2>
      </div>

      {/* 필터 바 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <label className="text-[12px] text-text-muted block mb-1">전략</label>
            <input
              type="text"
              list="strategy-list"
              value={strategySearch}
              onChange={(e) => handleStrategySelect(e.target.value)}
              placeholder="전략명 검색"
              className="h-8 px-3 rounded-lg border border-border bg-bg text-[13px] text-text w-48 outline-none placeholder:text-text-muted focus:border-primary"
            />
            <datalist id="strategy-list">
              {(strategies ?? []).map((s) => (
                <option key={s.id} value={s.name} />
              ))}
            </datalist>
          </div>
          <div>
            <label className="text-[12px] text-text-muted block mb-1">기간</label>
            <div className="flex gap-1 bg-bg rounded-lg p-0.5">
              {tabConfig.map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={`px-3 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
                    tab === key
                      ? 'bg-surface text-text'
                      : 'bg-transparent text-text-muted'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[12px] text-text-muted block mb-1">시작일</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="h-8 px-3 rounded-lg border border-border bg-bg text-[13px] text-text outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-[12px] text-text-muted block mb-1">종료일</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="h-8 px-3 rounded-lg border border-border bg-bg text-[13px] text-text outline-none focus:border-primary"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={handleQuery}
              className="h-8 px-4 rounded-lg bg-primary text-text text-[13px] font-medium border-none cursor-pointer hover:opacity-90 mt-4"
            >
              조회
            </button>
          </div>
        </div>
      </div>

      {/* 요약 카드 */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard
          label="조회 기간 실현 손익"
          value={formatKRW(totalPnl)}
          colorClass={totalPnl >= 0 ? 'text-positive' : 'text-negative'}
        />
        <StatCard label="총 거래 수" value={String(totalTrades)} />
        <StatCard label="승률" value={formatPercent(winRate)} />
        <StatCard
          label="수익 팩터"
          value={profitFactor == null ? '-' : profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}
        />
      </div>

      {/* 기간별 성과 테이블 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-4">
          {tab === 'daily' && '일별 성과'}
          {tab === 'weekly' && '주별 성과'}
          {tab === 'monthly' && '월별 성과'}
        </h3>

        {tab === 'daily' && (
          <>
            <DailyTable items={daily} offset={dailyOffset} startDate={appliedStartDate} endDate={appliedEndDate} />
            {daily.length > DAILY_PAGE_SIZE && (
              <Pagination
                total={daily.length}
                offset={dailyOffset}
                limit={DAILY_PAGE_SIZE}
                onPageChange={setDailyOffset}
              />
            )}
          </>
        )}

        {tab === 'weekly' && (
          <>
            <WeeklyTable items={weekly} offset={weeklyOffset} startDate={appliedStartDate} endDate={appliedEndDate} />
            {weekly.length > WEEKLY_PAGE_SIZE && (
              <Pagination
                total={weekly.length}
                offset={weeklyOffset}
                limit={WEEKLY_PAGE_SIZE}
                onPageChange={setWeeklyOffset}
              />
            )}
          </>
        )}

        {tab === 'monthly' && (
          <>
            <MonthlyTable items={monthly} offset={monthlyOffset} startDate={appliedStartDate} endDate={appliedEndDate} />
            {monthly.length > MONTHLY_PAGE_SIZE && (
              <Pagination
                total={monthly.length}
                offset={monthlyOffset}
                limit={MONTHLY_PAGE_SIZE}
                onPageChange={setMonthlyOffset}
              />
            )}
          </>
        )}
      </div>
    </>
  )
}
