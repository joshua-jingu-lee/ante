import { Link } from 'react-router-dom'
import { useApprovals, useUpdateApprovalStatus } from '../../hooks/useApprovals'
import { formatDateTime } from '../../utils/formatters'
import StatusBadge from '../common/StatusBadge'
import { TableSkeleton } from '../common/Skeleton'
import type { Approval } from '../../types/approval'

const TYPE_LABELS: Record<string, { label: string; variant: string }> = {
  strategy_report: { label: '전략 리포트', variant: 'info' },
  budget_allocate: { label: '예산 할당', variant: 'primary' },
  live_switch: { label: '실전 전환', variant: 'warning' },
  risk_alert: { label: '위험 알림', variant: 'negative' },
  // 레거시 타입 호환
  strategy_adopt: { label: '전략 채택', variant: 'info' },
  budget_change: { label: '예산 변경', variant: 'primary' },
  bot_create: { label: '봇 생성', variant: 'positive' },
  bot_stop: { label: '봇 중지', variant: 'warning' },
  rule_change: { label: '규칙 변경', variant: 'negative' },
}

export default function PendingApprovals() {
  const { data, isLoading } = useApprovals({ status: 'pending', limit: 5 })
  const updateStatus = useUpdateApprovalStatus()

  const items = data?.items ?? []
  const total = data?.total ?? 0

  const handleAction = (id: string, status: 'approved' | 'rejected') => {
    updateStatus.mutate({ id, status })
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <span className="text-[15px] font-semibold">승인 대기</span>
          {total > 0 && (
            <StatusBadge variant="negative">{total}건</StatusBadge>
          )}
        </div>
        <Link
          to="/approvals"
          className="px-2.5 py-1.5 text-[12px] text-text-muted bg-transparent rounded-lg hover:bg-surface-hover hover:text-text no-underline"
        >
          전체 보기 →
        </Link>
      </div>

      {isLoading ? (
        <TableSkeleton rows={3} cols={4} />
      ) : items.length === 0 ? (
        <div className="py-8 text-center text-text-muted text-[13px]">승인 대기 건이 없습니다</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">유형</th>
                <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">제목</th>
                <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">요청일</th>
                <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item: Approval, idx: number) => {
                const typeInfo = TYPE_LABELS[item.type] || { label: item.type, variant: 'muted' }
                const isLast = idx === items.length - 1
                const borderCls = isLast ? '' : 'border-b border-border'
                return (
                  <tr key={item.id} className="hover:bg-surface-hover">
                    <td className={`px-3 py-3 text-[13px] ${borderCls}`}>
                      <StatusBadge variant={typeInfo.variant as 'info'}>{typeInfo.label}</StatusBadge>
                    </td>
                    <td className={`px-3 py-3 text-[13px] ${borderCls}`}>
                      <Link to={`/approvals/${item.id}`} className="text-primary no-underline hover:underline">
                        {item.title}
                      </Link>
                    </td>
                    <td className={`px-3 py-3 text-[13px] text-text-muted ${borderCls}`}>
                      {formatDateTime(item.requested_at)}
                    </td>
                    <td className={`px-3 py-3 text-[13px] text-right ${borderCls}`}>
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => handleAction(item.id, 'approved')}
                          className="px-2.5 py-1 rounded-lg text-[12px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover"
                        >
                          승인
                        </button>
                        <button
                          onClick={() => handleAction(item.id, 'rejected')}
                          className="px-2.5 py-1 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text"
                        >
                          거부
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
