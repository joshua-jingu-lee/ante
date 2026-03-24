import { useFeedStatus } from '../../hooks/useFeed'
import { formatDateTime, formatNumber } from '../../utils/formatters'
import StatusBadge from '../common/StatusBadge'
import { Skeleton } from '../common/Skeleton'
import type { FeedCheckpoint, FeedReport } from '../../types/feed'

const SOURCE_LABELS: Record<string, string> = {
  data_go_kr: 'data.go.kr',
  dart: 'DART',
  pykrx: 'pykrx',
}

const DATA_TYPE_LABELS: Record<string, string> = {
  ohlcv: 'OHLCV (시세)',
  fundamental: '재무제표',
  flow: '수급',
  event: '기업 이벤트',
}

const MODE_LABELS: Record<string, string> = {
  daily: '일일 수집',
  backfill: '백필',
}

export default function FeedStatusPanel() {
  const { data: feedStatus, isLoading } = useFeedStatus()

  if (isLoading) {
    return (
      <div className="bg-surface border border-border rounded-lg p-5 mb-4">
        <Skeleton className="h-5 w-40 mb-4" />
        <Skeleton className="h-20 w-full" />
      </div>
    )
  }

  if (!feedStatus) return null

  const { initialized, checkpoints, recent_reports } = feedStatus
  const latestReport = recent_reports.length > 0 ? recent_reports[0] : null

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[15px] font-semibold text-text">Feed 파이프라인</span>
        {initialized ? (
          <StatusBadge variant="positive">활성</StatusBadge>
        ) : (
          <StatusBadge variant="muted">미초기화</StatusBadge>
        )}
      </div>

      {!initialized ? (
        <div className="text-[13px] text-text-muted">
          Feed가 초기화되지 않았습니다. <code className="bg-code-bg px-1.5 py-0.5 rounded-sm text-[12px]">ante feed init</code> 명령으로 초기화하세요.
        </div>
      ) : (
        <div className="space-y-4">
          {/* 최근 실행 결과 */}
          {latestReport && <LatestReportCard report={latestReport} />}

          {/* 소스별 체크포인트 현황 */}
          {checkpoints.length > 0 && (
            <div>
              <h4 className="text-[13px] font-semibold text-text-muted mb-2">소스별 수집 현황</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {checkpoints.map((cp) => (
                  <CheckpointCard key={`${cp.source}_${cp.data_type}`} checkpoint={cp} />
                ))}
              </div>
            </div>
          )}

          {checkpoints.length === 0 && !latestReport && (
            <div className="text-[13px] text-text-muted">
              아직 수집이 실행되지 않았습니다. <code className="bg-code-bg px-1.5 py-0.5 rounded-sm text-[12px]">ante feed run daily</code> 또는 <code className="bg-code-bg px-1.5 py-0.5 rounded-sm text-[12px]">ante feed run backfill</code> 명령으로 수집을 시작하세요.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function LatestReportCard({ report }: { report: FeedReport }) {
  const isSuccess = report.summary.symbols_failed === 0
  const hasWarnings = report.failures.length > 0 || report.warnings.length > 0

  return (
    <div>
      <h4 className="text-[13px] font-semibold text-text-muted mb-2">마지막 실행</h4>
      <div className="bg-bg rounded-lg border border-border p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-text">
              {MODE_LABELS[report.mode] ?? report.mode}
            </span>
            {isSuccess ? (
              <StatusBadge variant="positive">성공</StatusBadge>
            ) : hasWarnings ? (
              <StatusBadge variant="warning">일부 실패</StatusBadge>
            ) : (
              <StatusBadge variant="negative">실패</StatusBadge>
            )}
          </div>
          <span className="text-[12px] text-text-muted">
            {formatDateTime(report.finished_at)}
          </span>
        </div>
        <div className="flex items-center gap-4 text-[12px] text-text-muted">
          <span>대상: {report.target_date}</span>
          <span>종목: {formatNumber(report.summary.symbols_success)}/{formatNumber(report.summary.symbols_total)}</span>
          <span>기록: {formatNumber(report.summary.rows_written)}행</span>
          <span>소요: {report.duration_seconds}초</span>
        </div>
        {report.summary.symbols_failed > 0 && (
          <div className="mt-2 text-[12px] text-warning">
            {report.summary.symbols_failed}개 종목 수집 실패
          </div>
        )}
      </div>
    </div>
  )
}

function CheckpointCard({ checkpoint }: { checkpoint: FeedCheckpoint }) {
  return (
    <div className="bg-bg rounded-lg border border-border p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[13px] font-medium text-text">
          {SOURCE_LABELS[checkpoint.source] ?? checkpoint.source}
        </span>
        <span className="text-[11px] text-text-muted">
          {DATA_TYPE_LABELS[checkpoint.data_type] ?? checkpoint.data_type}
        </span>
      </div>
      <div className="text-[12px] text-text-muted">
        <span>마지막 수집: {checkpoint.last_date}</span>
        <span className="ml-3">갱신: {formatDateTime(checkpoint.updated_at)}</span>
      </div>
    </div>
  )
}
