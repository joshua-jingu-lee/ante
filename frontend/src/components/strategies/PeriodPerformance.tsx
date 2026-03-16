import { useState } from 'react'
import { formatKRW, formatPercent } from '../../utils/formatters'
import type { DailySummary, MonthlySummary } from '../../types/strategy'

type PeriodTab = 'daily' | 'monthly'

interface PeriodPerformanceProps {
  daily: DailySummary[] | undefined
  monthly: MonthlySummary[] | undefined
}

export default function PeriodPerformance({ daily, monthly }: PeriodPerformanceProps) {
  const [tab, setTab] = useState<PeriodTab>('daily')

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-semibold">기간별 성과</h3>
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          <button onClick={() => setTab('daily')} className={`px-3 py-1 rounded text-[12px] font-medium border-none cursor-pointer ${tab === 'daily' ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}>일별</button>
          <button onClick={() => setTab('monthly')} className={`px-3 py-1 rounded text-[12px] font-medium border-none cursor-pointer ${tab === 'monthly' ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}>월별</button>
        </div>
      </div>

      {tab === 'daily' && (
        <DailyTable items={daily ?? []} />
      )}
      {tab === 'monthly' && (
        <MonthlyTable items={monthly ?? []} />
      )}
    </div>
  )
}

function DailyTable({ items }: { items: DailySummary[] }) {
  if (items.length === 0) return <div className="py-4 text-text-muted text-[13px] text-center">데이터가 없습니다</div>

  const recent = items.slice(-10).reverse()

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">날짜</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">손익</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">거래수</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">승률</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((d) => (
            <tr key={d.date} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{d.date}</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${d.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>{formatKRW(d.realized_pnl)}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{d.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(d.win_rate)}</td>
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
            <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">기간</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">손익</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">거래수</th>
            <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">승률</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((m) => (
            <tr key={`${m.year}-${m.month}`} className="hover:bg-surface-hover">
              <td className="px-3 py-2.5 border-b border-border text-[13px]">{m.year}년 {m.month}월</td>
              <td className={`px-3 py-2.5 border-b border-border text-[13px] text-right ${m.realized_pnl >= 0 ? 'text-positive' : 'text-negative'}`}>{formatKRW(m.realized_pnl)}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{m.trade_count}</td>
              <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatPercent(m.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
