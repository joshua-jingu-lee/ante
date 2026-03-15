import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatDateTime } from '../../utils/formatters'
import type { Approval, ApprovalStatus, ApprovalType } from '../../types/approval'
import { APPROVAL_STATUS_LABELS } from '../../utils/constants'

const TYPE_BADGE: Record<ApprovalType, { label: string; variant: string }> = {
  strategy_report: { label: '전략 리포트', variant: 'info' },
  budget_allocation: { label: '예산 할당', variant: 'primary' },
  live_switch: { label: '실전 전환', variant: 'warning' },
  risk_alert: { label: '위험 알림', variant: 'negative' },
}

const STATUS_VARIANT: Record<ApprovalStatus, string> = {
  pending: 'warning',
  approved: 'positive',
  rejected: 'negative',
}

export default function ApprovalTable({ items }: { items: Approval[] }) {
  const navigate = useNavigate()

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">유형</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">제목</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">요청자</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">요청일</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">상태</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">결재 항목이 없습니다</td>
            </tr>
          ) : (
            items.map((item) => {
              const typeInfo = TYPE_BADGE[item.type] || { label: item.type, variant: 'muted' }
              return (
                <tr
                  key={item.id}
                  onClick={() => navigate(`/approvals/${item.id}`)}
                  className="hover:bg-surface-hover cursor-pointer"
                >
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <StatusBadge variant={typeInfo.variant as 'info'}>{typeInfo.label}</StatusBadge>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">{item.title}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{item.requester}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{formatDateTime(item.requested_at)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <StatusBadge variant={STATUS_VARIANT[item.status] as 'warning'}>
                      {APPROVAL_STATUS_LABELS[item.status] || item.status}
                    </StatusBadge>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
