import { useParams } from 'react-router-dom'
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
    </div>
  )
}

/* ── 백테스트 설정 카드 (R-2) ── */
function BacktestSettingsCard({ report }: { report: ReportDetailType }) {
  const config = report.config
  const datasets = report.datasets ?? []
  const symbols = datasets.map((d) => d.symbol)

  if (!config && datasets.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-3">백테스트 설정</h3>
        <div className="text-[13px] text-text-muted py-4 text-center">설정 정보 없음</div>
      </div>
    )
  }

  const formatRate = (value: number | undefined): string => {
    if (value == null) return '-'
    return `${(value * 100).toFixed(3)}%`
  }

  const renderSymbols = () => {
    if (symbols.length === 0) return '-'
    if (symbols.length <= 3) {
      return symbols.map((s, i) => (
        <span key={s}>
          {i > 0 && ', '}
          <span className="font-mono">{s}</span>
        </span>
      ))
    }
    return (
      <>
        <span className="font-mono">{symbols[0]}</span>
        {', '}
        <span className="font-mono">{symbols[1]}</span>
        {' '}
        <span className="text-text-muted">외 {symbols.length - 2}</span>
      </>
    )
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-3">백테스트 설정</h3>
      <InfoRow label="백테스트 기간" value={report.backtest_period || '-'} />
      <InfoRow label="초기 자금" value={config?.initial_balance != null ? `${config.initial_balance.toLocaleString()}원` : formatCurrency(report.initial_balance)} />
      <InfoRow label="타임프레임" value={config?.timeframe ?? '-'} />
      <InfoRow label="매수 수수료율" value={formatRate(config?.buy_commission_rate)} />
      <InfoRow label="매도 수수료율" value={formatRate(config?.sell_commission_rate)} />
      <InfoRow label="슬리피지율" value={formatRate(config?.slippage_rate)} />
      <InfoRow label="대상 종목" value={<span>{renderSymbols()}</span>} />
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

      {/* 1행: 리포트 정보 | 백테스트 설정 | 백테스트 성과 (3열) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <ReportInfoCard report={report} />
        <BacktestSettingsCard report={report} />
        <PerformanceCard report={report} />
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
