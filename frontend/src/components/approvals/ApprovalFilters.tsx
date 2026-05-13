import { APPROVAL_TYPES, type ApprovalStatus, type ApprovalType } from '../../types/approval'
import { APPROVAL_TYPE_LABELS } from '../../utils/constants'

const STATUS_OPTIONS: { key: ApprovalStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'pending', label: '대기' },
  { key: 'approved', label: '승인' },
  { key: 'rejected', label: '거부' },
]

/**
 * Filter 옵션은 backend SSOT (``ApprovalType`` enum) 와 정확히 일치시킨다
 * (#1471 — split #1418/C). unknown type 은 filter 옵션에 포함하지 않는다 —
 * 필터는 known SSOT type 만 노출하고, unknown row 는 ``'all'`` 선택 시 명시
 * 라벨로 표시된다 (``approvalTypeLabel`` / ``ApprovalTable``).
 */
const TYPE_OPTIONS: { key: ApprovalType | 'all'; label: string }[] = [
  { key: 'all', label: '전체 유형' },
  ...APPROVAL_TYPES.map((value) => ({ key: value, label: APPROVAL_TYPE_LABELS[value] })),
]

interface ApprovalFiltersProps {
  status: ApprovalStatus | 'all'
  type: ApprovalType | 'all'
  search: string
  pendingCount: number
  onStatusChange: (s: ApprovalStatus | 'all') => void
  onTypeChange: (t: ApprovalType | 'all') => void
  onSearchChange: (q: string) => void
}

export default function ApprovalFilters({ status, type, search, pendingCount, onStatusChange, onTypeChange, onSearchChange }: ApprovalFiltersProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap mb-4">
      <div className="flex gap-1 bg-bg rounded-lg p-0.5">
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => onStatusChange(opt.key)}
            className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
              status === opt.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
            }`}
          >
            {opt.key === 'pending' && pendingCount > 0
              ? `${opt.label} (${pendingCount})`
              : opt.label}
          </button>
        ))}
      </div>
      <select
        value={type}
        onChange={(e) => onTypeChange(e.target.value as ApprovalType | 'all')}
        className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] min-w-[140px] focus:outline-none focus:border-primary cursor-pointer"
      >
        {TYPE_OPTIONS.map((opt) => (
          <option key={opt.key} value={opt.key}>{opt.label}</option>
        ))}
      </select>
      <input
        type="text"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        placeholder="제목, 전략명 검색..."
        className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] w-[240px] focus:outline-none focus:border-primary"
      />
    </div>
  )
}
