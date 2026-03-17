import { Link, useParams } from 'react-router-dom'
import { useReportDetail } from '../hooks/useReports'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatDateTime } from '../utils/formatters'
import type { ReportDetail as ReportDetailType, ReportStatus } from '../types/report'

const STATUS_BADGE: Record<ReportStatus, { label: string; variant: string }> = {
  draft: { label: '초안', variant: 'muted' },
  submitted: { label: '제출됨', variant: 'warning' },
  reviewed: { label: '검토됨', variant: 'info' },
  adopted: { label: '채택됨', variant: 'positive' },
  rejected: { label: '거부됨', variant: 'negative' },
  archived: { label: '보관됨', variant: 'muted' },
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-border last:border-b-0 text-[13px]">
      <span className="text-text-muted">{label}</span>
      <span>{value}</span>
    </div>
  )
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '-'
  return `${value.toLocaleString()}원`
}

function formatPct(value: number | null | undefined, sign = false): string {
  if (value == null) return '-'
  const prefix = sign && value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(1)}%`
}

/* ── 리포트 정보 카드 ── */
function ReportInfoCard({ report }: { report: ReportDetailType }) {
  const status = STATUS_BADGE[report.status] || { label: report.status, variant: 'muted' }
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">리포트 정보</h3>
      <InfoRow label="리포트 ID" value={<span className="font-mono text-[12px]">{report.report_id}</span>} />
      <InfoRow label="전략명" value={<span className="font-mono text-[12px]">{report.strategy_name}</span>} />
      <InfoRow label="버전" value={report.strategy_version} />
      <InfoRow label="상태" value={<StatusBadge variant={status.variant as 'info'}>{status.label}</StatusBadge>} />
      <InfoRow label="수행자" value={report.submitted_by} />
      <InfoRow label="수행일" value={formatDateTime(report.submitted_at)} />
      <InfoRow label="백테스트 기간" value={report.backtest_period || '-'} />
    </div>
  )
}

/* ── 백테스트 성과 카드 ── */
function PerformanceCard({ report }: { report: ReportDetailType }) {
  const initialBalance = report.initial_balance ?? 0
  const returnAmount = initialBalance * (report.total_return_pct / 100)
  const mddAmount = initialBalance * ((report.max_drawdown_pct ?? 0) / 100)

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">백테스트 성과</h3>
      <InfoRow
        label="누적 수익률"
        value={
          <span className={`font-semibold ${report.total_return_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
            {formatPct(report.total_return_pct, true)} ({returnAmount >= 0 ? '+' : ''}{formatCurrency(Math.round(returnAmount))})
          </span>
        }
      />
      <InfoRow label="총 거래 수" value={`${report.total_trades}회`} />
      <InfoRow label="승률" value={formatPct(report.win_rate)} />
      <InfoRow label="수익 팩터" value={report.metrics?.profit_factor?.toFixed(2) ?? '-'} />
      <InfoRow label="샤프 비율" value={report.sharpe_ratio?.toFixed(2) ?? '-'} />
      <InfoRow
        label="최대 낙폭"
        value={
          <span className="font-semibold text-negative">
            {formatPct(report.max_drawdown_pct)} ({formatCurrency(Math.round(mddAmount))})
          </span>
        }
      />
      <InfoRow label="평균 수익" value={<span className="text-positive">{formatCurrency(report.metrics?.avg_profit ? Math.round(report.metrics.avg_profit) : null)}</span>} />
      <InfoRow label="평균 손실" value={<span className="text-negative">{formatCurrency(report.metrics?.avg_loss ? Math.round(report.metrics.avg_loss) : null)}</span>} />
      <InfoRow label="수수료 합계" value={<span className="text-text-muted">{formatCurrency(report.metrics?.total_commission ? Math.round(report.metrics.total_commission) : null)}</span>} />
      <InfoRow label="활성 거래일" value={report.metrics?.active_days ? `${report.metrics.active_days}일` : '-'} />
    </div>
  )
}

/* ── 백테스트 데이터 카드 ── */
function BacktestDataCard({ report }: { report: ReportDetailType }) {
  const symbols = report.symbols ?? []
  const visible = symbols.slice(0, 3)
  const remaining = symbols.length - 3

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">백테스트 데이터</h3>
      <InfoRow label="초기 자금" value={formatCurrency(report.initial_balance)} />
      {symbols.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">종목</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">타임프레임</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">기간</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">행 수</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => (
                <tr key={s.symbol}>
                  <td className="px-3 py-2 border-b border-border text-[13px]">{s.name} ({s.symbol})</td>
                  <td className="px-3 py-2 border-b border-border text-[13px]">{s.timeframe}</td>
                  <td className="px-3 py-2 border-b border-border text-[13px]">{s.period}</td>
                  <td className="px-3 py-2 border-b border-border text-[13px] text-right">{s.rows.toLocaleString()}</td>
                </tr>
              ))}
              {remaining > 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-2 text-center text-[12px] text-text-muted">
                    외 {remaining}종목 · <Link to="/backtest-data" className="text-primary no-underline hover:underline">백테스트 데이터 관리</Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── 메인 페이지 ── */
export default function ReportDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: report, isLoading } = useReportDetail(id ?? '')

  if (isLoading) return <PageSkeleton />
  if (!report) return <div className="text-text-muted text-center py-12">리포트를 찾을 수 없습니다</div>

  return (
    <>
      {/* 헤더 */}
      <div className="mb-6">
        <h2 className="text-[20px] font-bold">{report.strategy_name} {report.strategy_version} 검증 리포트</h2>
      </div>

      {/* 1행: 리포트 정보 | 백테스트 성과 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ReportInfoCard report={report} />
        <PerformanceCard report={report} />
      </div>

      {/* 2행: 백테스트 데이터 */}
      <div className="mb-6">
        <BacktestDataCard report={report} />
      </div>

      {/* 3행: 자산 곡선 차트 (플레이스홀더) */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">자산 곡선</h3>
        <div className="h-[240px] bg-bg-elevated rounded flex items-center justify-center text-text-muted text-[13px]">
          equity_curve 차트 영역 (detail_json.equity_curve 데이터 기반)
        </div>
      </div>

      {/* 4행: 전략 요약 | 리스크 분석 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">전략 요약</h3>
          <div className="text-[13px] text-text-muted leading-relaxed space-y-3">
            {report.summary && (
              <div>
                <div className="text-text font-semibold mb-1">요약</div>
                <p>{report.summary}</p>
              </div>
            )}
            {report.rationale && (
              <div>
                <div className="text-text font-semibold mb-1">근거</div>
                <p>{report.rationale}</p>
              </div>
            )}
          </div>
        </div>
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">리스크 분석</h3>
          <div className="text-[13px] text-text-muted leading-relaxed space-y-3">
            {report.risks && (
              <div>
                <div className="text-text font-semibold mb-1">위험 요소</div>
                <p>{report.risks}</p>
              </div>
            )}
            {report.recommendations && (
              <div>
                <div className="text-text font-semibold mb-1">권장 사항</div>
                <p>{report.recommendations}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
