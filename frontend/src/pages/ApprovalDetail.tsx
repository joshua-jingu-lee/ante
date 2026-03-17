import { Link, useParams } from 'react-router-dom'
import { useApprovalDetail } from '../hooks/useApprovals'
import ReviewControls from '../components/approvals/ReviewControls'
import ExecutionContent from '../components/approvals/ExecutionContent'
import MarkdownBody from '../components/approvals/MarkdownBody'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatDateTime } from '../utils/formatters'
import { APPROVAL_STATUS_LABELS } from '../utils/constants'
import type { Approval, ApprovalStatus, ApprovalType, ApprovalReview, ApprovalHistoryEntry } from '../types/approval'

const STATUS_VARIANT: Record<ApprovalStatus, string> = {
  pending: 'warning',
  approved: 'positive',
  rejected: 'negative',
}

const TYPE_LABEL: Record<ApprovalType, string> = {
  strategy_adopt: '전략 채택',
  budget_change: '예산 변경',
  bot_create: '봇 생성',
  bot_stop: '봇 중지',
  rule_change: '규칙 변경',
}

const REVIEW_RESULT_VARIANT: Record<string, string> = {
  pass: 'positive',
  warn: 'warning',
  fail: 'negative',
}

const ACTOR_COLOR: Record<string, string> = {
  user: 'text-positive',
  rule_engine: 'text-text-muted',
  treasury: 'text-text-muted',
}

function getActorColor(actor: string): string {
  if (actor in ACTOR_COLOR) return ACTOR_COLOR[actor]
  if (actor.startsWith('agent:')) return 'text-primary'
  return 'text-text-muted'
}

/* ── 결재 정보 카드 ── */
function ApprovalInfoCard({ approval }: { approval: Approval }) {
  const typeLabel = TYPE_LABEL[approval.type] || approval.type
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">결재 정보</h3>
      <div className="space-y-0">
        <InfoRow label="요청자" value={approval.requester} />
        <InfoRow label="유형" value={typeLabel} />
        <InfoRow label="상태" value={
          <StatusBadge variant={STATUS_VARIANT[approval.status] as 'warning'}>
            {APPROVAL_STATUS_LABELS[approval.status]}
          </StatusBadge>
        } />
        <InfoRow label="요청일" value={formatDateTime(approval.requested_at)} />
        {approval.expires_at && <InfoRow label="만료일" value={formatDateTime(approval.expires_at)} />}
        {approval.resolved_at && <InfoRow label="처리일" value={formatDateTime(approval.resolved_at)} />}
        {approval.resolved_by && <InfoRow label="처리자" value={approval.resolved_by} />}
        {approval.reference_id && (
          <InfoRow label="참조 리포트" value={
            <Link to={`/reports/${approval.reference_id}`} className="text-primary no-underline hover:underline font-mono text-[12px]">
              {approval.reference_id}
            </Link>
          } />
        )}
      </div>
    </div>
  )
}

/* ── 검토 의견 카드 ── */
function ReviewsCard({ reviews }: { reviews: ApprovalReview[] }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">검토 의견</h3>
      {reviews.length === 0 ? (
        <div className="text-[13px] text-text-muted py-4 text-center">검토 의견이 없습니다</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">검증 주체</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">결과</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">상세</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">검증 시각</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((r, i) => (
                <tr key={i}>
                  <td className="px-3 py-2.5 border-b border-border text-[13px] font-mono">{r.reviewer}</td>
                  <td className="px-3 py-2.5 border-b border-border text-[13px]">
                    <StatusBadge variant={(REVIEW_RESULT_VARIANT[r.result] ?? 'muted') as 'positive'}>
                      {r.result}
                    </StatusBadge>
                  </td>
                  <td className="px-3 py-2.5 border-b border-border text-[12px] text-text-muted max-w-[300px]">{r.detail}</td>
                  <td className="px-3 py-2.5 border-b border-border text-[13px] text-text-muted whitespace-nowrap">{formatDateTime(r.reviewed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── 감사 이력 카드 ── */
function AuditHistoryCard({ history }: { history: ApprovalHistoryEntry[] }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">감사 이력</h3>
      {history.length === 0 ? (
        <div className="text-[13px] text-text-muted py-4 text-center">이력이 없습니다</div>
      ) : (
        <div className="space-y-0">
          {history.map((entry, i) => (
            <div key={i} className="flex items-start gap-4 py-2.5 border-b border-border last:border-b-0">
              <span className="text-[12px] text-text-muted whitespace-nowrap min-w-[130px]">{formatDateTime(entry.at)}</span>
              <span className="text-[13px]">
                <span className={`font-mono ${getActorColor(entry.actor)}`}>{entry.actor}</span>
                {' — '}
                {entry.detail || entry.action}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── 공통 InfoRow ── */
function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-border last:border-b-0 text-[13px]">
      <span className="text-text-muted">{label}</span>
      <span>{value}</span>
    </div>
  )
}

/* ── 메인 페이지 ── */
export default function ApprovalDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: approval, isLoading } = useApprovalDetail(id ?? '')

  if (isLoading) return <PageSkeleton />
  if (!approval) return <div className="text-text-muted text-center py-12">결재 항목을 찾을 수 없습니다</div>

  const isPending = approval.status === 'pending'

  return (
    <>
      {/* 상세 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-[20px] font-bold">{approval.title}</h2>
        {isPending && <ReviewControls approvalId={approval.id} isPending={isPending} />}
      </div>

      {/* 거부 사유 배너 */}
      {approval.reject_reason && (
        <div className="bg-negative/10 border border-negative/30 rounded-lg p-4 mb-6 text-[13px]">
          <div className="font-semibold text-negative mb-1">거부 사유</div>
          <div className="text-text-muted">{approval.reject_reason}</div>
        </div>
      )}

      {/* 1행: 결재 정보 | 검토 의견 (2열) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ApprovalInfoCard approval={approval} />
        <ReviewsCard reviews={approval.reviews ?? []} />
      </div>

      {/* 2행: 본문 */}
      {approval.body && (
        <div className="bg-surface border border-border rounded-lg p-5 mb-6">
          <MarkdownBody content={approval.body} />
        </div>
      )}

      {/* 3행: 실행 내용 */}
      <ExecutionContent type={approval.type} params={approval.params} />

      {/* 4행: 감사 이력 */}
      <AuditHistoryCard history={approval.history ?? []} />
    </>
  )
}
