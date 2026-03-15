import type { ApprovalStatus, ApprovalType } from '../../types/approval'

const STATUS_OPTIONS: { key: ApprovalStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'pending', label: '대기' },
  { key: 'approved', label: '승인' },
  { key: 'rejected', label: '거부' },
]

const TYPE_OPTIONS: { key: ApprovalType | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'strategy_report', label: '전략 리포트' },
  { key: 'budget_allocation', label: '예산 할당' },
  { key: 'live_switch', label: '실전 전환' },
  { key: 'risk_alert', label: '위험 알림' },
]

interface ApprovalFiltersProps {
  status: ApprovalStatus | 'all'
  type: ApprovalType | 'all'
  onStatusChange: (s: ApprovalStatus | 'all') => void
  onTypeChange: (t: ApprovalType | 'all') => void
}

export default function ApprovalFilters({ status, type, onStatusChange, onTypeChange }: ApprovalFiltersProps) {
  return (
    <div className="flex items-center gap-3 mb-4 flex-wrap">
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
          </button>
        ))}
      </div>
      <select
        value={type}
        onChange={(e) => onTypeChange(e.target.value as ApprovalType | 'all')}
        className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] cursor-pointer"
      >
        {TYPE_OPTIONS.map((opt) => (
          <option key={opt.key} value={opt.key}>{opt.label}</option>
        ))}
      </select>
    </div>
  )
}
