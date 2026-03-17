import { useParams } from 'react-router-dom'
import { useApprovalDetail } from '../hooks/useApprovals'
import ReviewControls from '../components/approvals/ReviewControls'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatDateTime } from '../utils/formatters'
import { APPROVAL_STATUS_LABELS } from '../utils/constants'
import type { ApprovalStatus, ApprovalType } from '../types/approval'

const STATUS_VARIANT: Record<ApprovalStatus, string> = {
  pending: 'warning',
  approved: 'positive',
  rejected: 'negative',
}

const TYPE_BADGE: Record<ApprovalType, { label: string; variant: string }> = {
  strategy_adopt: { label: '전략 채택', variant: 'info' },
  budget_change: { label: '예산 변경', variant: 'primary' },
  bot_create: { label: '봇 생성', variant: 'positive' },
  bot_stop: { label: '봇 중지', variant: 'warning' },
  rule_change: { label: '규칙 변경', variant: 'negative' },
}

export default function ApprovalDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: approval, isLoading } = useApprovalDetail(id ?? '')

  if (isLoading) return <PageSkeleton />
  if (!approval) return <div className="text-text-muted text-center py-12">결재 항목을 찾을 수 없습니다</div>

  const isPending = approval.status === 'pending'
  const typeInfo = TYPE_BADGE[approval.type] || { label: approval.type, variant: 'muted' }

  return (
    <>
      {/* 상세 헤더 */}
      <div className="mb-6">
        <h2 className="text-[20px] font-bold mb-2">{approval.title}</h2>
        <div className="flex items-center gap-3 flex-wrap">
          <StatusBadge variant={typeInfo.variant as 'info'}>{typeInfo.label}</StatusBadge>
          <StatusBadge variant={STATUS_VARIANT[approval.status] as 'warning'}>
            {APPROVAL_STATUS_LABELS[approval.status]}
          </StatusBadge>
          <span className="text-[13px] text-text-muted">
            요청: {approval.requester} | {formatDateTime(approval.requested_at)}
          </span>
        </div>
      </div>

      {/* 거부 사유 배너 */}
      {approval.reject_reason && (
        <div className="bg-negative/10 border border-negative/30 rounded-lg p-4 mb-6 text-[13px] text-negative">
          <span className="font-semibold">거부 사유:</span> {approval.reject_reason}
        </div>
      )}

      {/* 결재 정보 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">결재 정보</h3>
        <div className="space-y-2">
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">유형</span>
            <span>{typeInfo.label}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">요청자</span>
            <span>{approval.requester}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">요청일</span>
            <span>{formatDateTime(approval.requested_at)}</span>
          </div>
          {approval.expires_at && (
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">만료일</span>
              <span>{formatDateTime(approval.expires_at)}</span>
            </div>
          )}
          {approval.resolved_at && (
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">처리일</span>
              <span>{formatDateTime(approval.resolved_at)}</span>
            </div>
          )}
          {approval.resolved_by && (
            <div className="flex justify-between py-2 text-[13px]">
              <span className="text-text-muted">처리자</span>
              <span>{approval.resolved_by}</span>
            </div>
          )}
        </div>
      </div>

      {/* 결재 영역 */}
      <ReviewControls approvalId={approval.id} isPending={isPending} />
    </>
  )
}
