import { Link } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatDateTime } from '../../utils/formatters'
import type { Approval, ApprovalStatus, ApprovalType } from '../../types/approval'
import { APPROVAL_STATUS_LABELS } from '../../utils/constants'

const TYPE_LABEL: Record<ApprovalType, string> = {
  strategy_adopt: '전략 채택',
  strategy_report: '전략 리포트',
  budget_change: '예산 변경',
  budget_allocate: '예산 할당',
  bot_create: '봇 생성',
  bot_stop: '봇 중지',
  live_switch: '실전 전환',
  risk_alert: '위험 알림',
  rule_change: '규칙 변경',
}

const STATUS_VARIANT: Record<ApprovalStatus, string> = {
  pending: 'warning',
  approved: 'positive',
  rejected: 'negative',
}

export default function ApprovalTable({ items }: { items: Approval[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">유형</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">제목</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">요청자</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">요청일</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">상태</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">처리일</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">결재 항목이 없습니다</td>
            </tr>
          ) : (
            items.map((item) => (
                <tr
                  key={item.id}
                  className="hover:bg-surface-hover"
                >
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <StatusBadge variant="muted">{TYPE_LABEL[item.type] || item.type}</StatusBadge>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <Link to={`/approvals/${item.id}`} className="text-primary no-underline hover:underline">
                      {item.title}
                    </Link>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <span className="text-primary">{item.requester}</span>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{formatDateTime(item.requested_at)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <StatusBadge variant={STATUS_VARIANT[item.status] as 'warning'}>
                      {APPROVAL_STATUS_LABELS[item.status] || item.status}
                    </StatusBadge>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{item.resolved_at ? formatDateTime(item.resolved_at) : '-'}</td>
                </tr>
              ))
          )}
        </tbody>
      </table>
    </div>
  )
}
