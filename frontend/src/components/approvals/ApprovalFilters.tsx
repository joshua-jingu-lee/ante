import type { ApprovalStatus, ApprovalType, Approval } from '../../types/approval'

const STATUS_OPTIONS: { key: ApprovalStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'pending', label: '대기' },
  { key: 'approved', label: '승인' },
  { key: 'rejected', label: '거부' },
]

const TYPE_OPTIONS: { key: ApprovalType | 'all'; label: string }[] = [
  { key: 'all', label: '전체 유형' },
  { key: 'strategy_report', label: '전략 리포트' },
  { key: 'budget_allocation', label: '예산 할당' },
  { key: 'live_switch', label: '실전 전환' },
  { key: 'risk_alert', label: '위험 알림' },
]

interface ApprovalFiltersProps {
  status: ApprovalStatus | 'all'
  type: ApprovalType | 'all'
  search: string
  items?: Approval[]
  onStatusChange: (s: ApprovalStatus | 'all') => void
  onTypeChange: (t: ApprovalType | 'all') => void
  onSearchChange: (q: string) => void
}

export default function ApprovalFilters({ status, type, search, items, onStatusChange, onTypeChange, onSearchChange }: ApprovalFiltersProps) {
  const counts: Record<string, number> = { all: 0, pending: 0, approved: 0, rejected: 0 }
  for (const item of items ?? []) {
    counts.all++
    if (item.status in counts) counts[item.status]++
  }

  return (
    <div className="space-y-3 mb-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => onStatusChange(opt.key)}
              className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
                status === opt.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
              }`}
            >
              {opt.label}
              {counts[opt.key] > 0 && (
                <span className="ml-1 bg-border text-text text-[11px] px-1.5 py-0.5 rounded-full">{counts[opt.key]}</span>
              )}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => onTypeChange(opt.key)}
              className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
                type === opt.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="제목, 전략명 검색..."
          className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] w-[240px] focus:outline-none focus:border-primary"
        />
      </div>
    </div>
  )
}
