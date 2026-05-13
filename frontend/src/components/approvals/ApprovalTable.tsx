import { Link } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatDateTime } from '../../utils/formatters'
import type { Approval, ApprovalDisplayType, ApprovalStatus } from '../../types/approval'
import { APPROVAL_STATUS_LABELS } from '../../utils/constants'

const TYPE_LABEL: Record<ApprovalDisplayType, string> = {
  strategy_adopt: '전략 채택',
  strategy_report: '전략 리포트',
  budget_change: '예산 변경',
  budget_allocate: '예산 할당',
  bot_create: '봇 생성',
  bot_stop: '봇 중지',
  live_switch: '실전 전환',
  risk_alert: '위험 알림',
  rule_change: '규칙 변경',
  strategy_retire: '전략 폐기',
  bot_assign_strategy: '봇 전략 배정',
  bot_change_strategy: '봇 전략 변경',
  bot_resume: '봇 재개',
  bot_delete: '봇 삭제',
  unknown: '알 수 없는 유형',
}

const TYPE_VARIANT: Record<ApprovalDisplayType, 'muted' | 'warning'> = {
  strategy_adopt: 'muted',
  strategy_report: 'muted',
  budget_change: 'muted',
  budget_allocate: 'muted',
  bot_create: 'muted',
  bot_stop: 'muted',
  live_switch: 'muted',
  risk_alert: 'muted',
  rule_change: 'muted',
  strategy_retire: 'muted',
  bot_assign_strategy: 'muted',
  bot_change_strategy: 'muted',
  bot_resume: 'muted',
  bot_delete: 'muted',
  unknown: 'warning',
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
                    <StatusBadge variant={TYPE_VARIANT[item.type]}>{TYPE_LABEL[item.type]}</StatusBadge>
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
