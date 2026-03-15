import { formatKRW } from '../../utils/formatters'
import type { TreasurySummary } from '../../types/treasury'

export default function AccountSummary({ summary }: { summary: TreasurySummary }) {
  const stats = [
    { label: '총 잔고', value: formatKRW(summary.total_balance) },
    { label: '할당됨', value: formatKRW(summary.allocated) },
    { label: '미할당', value: formatKRW(summary.unallocated) },
    { label: '예약됨', value: formatKRW(summary.reserved) },
  ]

  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      {stats.map((s) => (
        <div key={s.label} className="bg-surface border border-border rounded-lg px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">{s.label}</div>
          <div className="text-[24px] font-bold">{s.value}</div>
        </div>
      ))}
    </div>
  )
}
