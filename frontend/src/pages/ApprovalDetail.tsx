import { useParams } from 'react-router-dom'
import { useApprovalDetail } from '../hooks/useApprovals'
import ReviewControls from '../components/approvals/ReviewControls'
import BacktestMetricsPanel from '../components/approvals/BacktestMetrics'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatDate } from '../utils/formatters'
import { APPROVAL_STATUS_LABELS } from '../utils/constants'
import type { ApprovalStatus } from '../types/approval'

const STATUS_VARIANT: Record<ApprovalStatus, string> = {
  pending: 'warning',
  approved: 'positive',
  rejected: 'negative',
}

export default function ApprovalDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: approval, isLoading } = useApprovalDetail(Number(id))

  if (isLoading) return <PageSkeleton />
  if (!approval) return <div className="text-text-muted text-center py-12">결재 항목을 찾을 수 없습니다</div>

  const detail = approval.detail
  const isPending = approval.status === 'pending'

  return (
    <>
      {/* 결재 영역 */}
      <ReviewControls approvalId={approval.id} isPending={isPending} />

      {/* Agent 분석 */}
      {detail && (
        <div className="bg-surface border border-border rounded-lg p-5 mb-6">
          <h3 className="text-[15px] font-semibold mb-3">Agent 분석</h3>
          <div className="space-y-4 text-[13px]">
            <div>
              <div className="text-text-muted text-[12px] font-semibold mb-1">요약</div>
              <p>{detail.agent_summary}</p>
            </div>
            <div>
              <div className="text-text-muted text-[12px] font-semibold mb-1">근거</div>
              <p>{detail.agent_rationale}</p>
            </div>
            <div>
              <div className="text-text-muted text-[12px] font-semibold mb-1">리스크</div>
              <p>{detail.agent_risks}</p>
            </div>
            <div>
              <div className="text-text-muted text-[12px] font-semibold mb-1">권장 사항</div>
              <p>{detail.agent_recommendation}</p>
            </div>
          </div>
        </div>
      )}

      {/* 전략 정보 + 백테스트 요약 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">전략 정보</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">제목</span>
              <span>{approval.title}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">요청자</span>
              <span>{approval.requester}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">상태</span>
              <StatusBadge variant={STATUS_VARIANT[approval.status] as 'warning'}>
                {APPROVAL_STATUS_LABELS[approval.status]}
              </StatusBadge>
            </div>
            {detail && (
              <>
                <div className="flex justify-between py-2 border-b border-border text-[13px]">
                  <span className="text-text-muted">전략명</span>
                  <span>{detail.strategy_name}</span>
                </div>
                <div className="flex justify-between py-2 text-[13px]">
                  <span className="text-text-muted">버전</span>
                  <span>{detail.strategy_version}</span>
                </div>
              </>
            )}
          </div>
        </div>

        {detail && (
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-[15px] font-semibold mb-3">백테스트 요약</h3>
            <div className="space-y-2">
              <div className="flex justify-between py-2 border-b border-border text-[13px]">
                <span className="text-text-muted">시작일</span>
                <span>{formatDate(detail.backtest_start)}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-border text-[13px]">
                <span className="text-text-muted">종료일</span>
                <span>{formatDate(detail.backtest_end)}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-border text-[13px]">
                <span className="text-text-muted">총 거래</span>
                <span>{detail.metrics.total_trades}회</span>
              </div>
              <div className="flex justify-between py-2 text-[13px]">
                <span className="text-text-muted">총 수익률</span>
                <span className={detail.metrics.total_return >= 0 ? 'text-positive' : 'text-negative'}>
                  {(detail.metrics.total_return * 100).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 성과 지표 */}
      {detail && <BacktestMetricsPanel metrics={detail.metrics} />}

      {/* 차트 */}
      {detail && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-[15px] font-semibold mb-3">자산 추이</h3>
            <div className="h-[200px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
              📈 에쿼티 커브 (Area Chart)
            </div>
          </div>
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-[15px] font-semibold mb-3">드로우다운</h3>
            <div className="h-[200px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
              📉 드로우다운 (Area Chart)
            </div>
          </div>
        </div>
      )}
    </>
  )
}
