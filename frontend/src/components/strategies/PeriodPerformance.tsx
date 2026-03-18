import { useState } from 'react'
import { formatKRW, formatPercent } from '../../utils/formatters'
import type { DailySummary, WeeklySummary, MonthlySummary } from '../../types/strategy'

type PeriodTab = 'daily' | 'weekly' | 'monthly'

interface PeriodPerformanceProps {
  daily: DailySummary[] | undefined
  weekly: WeeklySummary[] | undefined
  monthly: MonthlySummary[] | undefined
  strategyId?: string
}

export default function PeriodPerformance({ daily, weekly, monthly, strategyId }: PeriodPerformanceProps) {
  const [tab, setTab] = useState<PeriodTab>('monthly')

  const tabBtn = (key: PeriodTab, label: string) => (
    <button
      onClick={() => setTab(key)}
      className={`px-3 py-1 rounded text-[12px] font-medium border-none cursor-pointer ${tab === key ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}
    >
      {label}
    </button>
  )

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-semibold">기간별 성과</h3>
        {strategyId && (
          <span className="text-[13px] text-primary cursor-pointer hover:underline">더 보기 &rarr;</span>
        )}
      </div>
      <div className="flex gap-1 bg-bg rounded-lg p-0.5 w-fit mb-4">
        {tabBtn('daily', '일별')}
        {tabBtn('weekly', '주별')}
        {tabBtn('monthly', '월별')}
      </div>

      {tab === 'daily' && <DailyTable items={daily ?? []} />}
      {tab === 'weekly' && <WeeklyTable items={weekly ?? []} />}
      {tab === 'monthly' && <MonthlyTable items={monthly ?? []} />}
    </div>
  )
}

function DailyTable({ items }: { items: DailySummary[] }) {
  if (items.length === 0) return <div className="py-4 text-text-muted text-[13px] text-center">데이터가 없습니다</div>

  const recent = items.slice(-12).reverse()

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
          {recent.map((d) => (
            <tr key={d.date} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{d.date}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{d.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(d.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${d.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>{formatKRW(d.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function WeeklyTable({ items }: { items: WeeklySummary[] }) {
  if (items.length === 0) return <div className="py-4 text-text-muted text-[13px] text-center">데이터가 없습니다</div>

  const recent = items.slice(-12).reverse()

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
          {recent.map((w) => (
            <tr key={w.week_label} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{w.week_label}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{w.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(w.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${w.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>{formatKRW(w.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MonthlyTable({ items }: { items: MonthlySummary[] }) {
  if (items.length === 0) return <div className="py-4 text-text-muted text-[13px] text-center">데이터가 없습니다</div>

  const recent = items.slice(-12).reverse()

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
          {recent.map((m) => (
            <tr key={`${m.year}-${m.month}`} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{m.year}-{String(m.month).padStart(2, '0')}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{m.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(m.win_rate)}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${m.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>{formatKRW(m.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
