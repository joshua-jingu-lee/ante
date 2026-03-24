import { useState, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useStrategyDetail, useStrategyPerformance, useStrategyTrades, useStrategyDailySummary, useStrategyWeeklySummary, useStrategyMonthlySummary, useStrategyStatusTransition } from '../hooks/useStrategies'
import PerformancePanel from '../components/strategies/PerformancePanel'
import PeriodPerformance from '../components/strategies/PeriodPerformance'
import EquityCurveChart from '../components/charts/EquityCurveChart'
import StatusBadge from '../components/common/StatusBadge'
import HintTooltip from '../components/common/HintTooltip'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatNumber } from '../utils/formatters'
import { STRATEGY_STATUS_LABELS } from '../utils/constants'
import type { StrategyStatus, StrategyParam } from '../types/strategy'

const STATUS_VARIANT: Record<StrategyStatus, string> = {
  active: 'positive', registered: 'warning', inactive: 'muted', archived: 'muted',
}

type EquityCurvePeriod = '1w' | '1m' | '3m' | 'all'

function isStrategyParam(v: unknown): v is StrategyParam {
  return typeof v === 'object' && v !== null && 'value' in v
}

function getPeriodDates(period: EquityCurvePeriod): { start?: Date } {
  if (period === 'all') return {}
  const now = new Date()
  const start = new Date(now)
  if (period === '1w') start.setDate(start.getDate() - 7)
  else if (period === '1m') start.setMonth(start.getMonth() - 1)
  else if (period === '3m') start.setMonth(start.getMonth() - 3)
  return { start }
}

export default function StrategyDetail() {
  const { id = '' } = useParams<{ id: string }>()
  const [equityPeriod, setEquityPeriod] = useState<EquityCurvePeriod>('1m')

  const { data: strategy, isLoading } = useStrategyDetail(id)
  const { data: performance } = useStrategyPerformance(id)
  const { data: tradesData } = useStrategyTrades(id)
  const { data: dailySummary } = useStrategyDailySummary(id)
  const { data: weeklySummary } = useStrategyWeeklySummary(id)
  const { data: monthlySummary } = useStrategyMonthlySummary(id)
  const statusTransition = useStrategyStatusTransition()

  const equityCurveData = useMemo(() => {
    const raw = performance?.equity_curve ?? []
    if (raw.length === 0) return []
    const { start } = getPeriodDates(equityPeriod)
    if (!start) return raw
    const startStr = start.toISOString().slice(0, 10)
    return raw.filter((p) => p.date >= startStr)
  }, [performance?.equity_curve, equityPeriod])

  if (isLoading) return <PageSkeleton />
  if (!strategy) return <div className="text-text-muted text-center py-12">전략을 찾을 수 없습니다</div>

  const status = strategy.status as StrategyStatus
  const hasRunningBot = !!strategy.bot_id && strategy.bot_status === 'running'
  const budgetAllocated = strategy.budget_allocated
  const unrealizedPnl = strategy.unrealized_pnl

  const handleStatusTransition = (newStatus: string) => {
    statusTransition.mutate({ id, status: newStatus })
  }

  return (
    <>
      {/* 전략 정보 헤더 */}
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <h2 className="text-[18px] font-bold">{strategy.name}</h2>
          <StatusActionButtons
            status={status}
            hasRunningBot={hasRunningBot}
            isPending={statusTransition.isPending}
            onTransition={handleStatusTransition}
          />
        </div>
        <div className="flex gap-3 items-center mt-1">
          <StatusBadge variant={(STATUS_VARIANT[status] ?? 'muted') as 'positive'}>
            {STRATEGY_STATUS_LABELS[strategy.status]}
          </StatusBadge>
          <span className="text-text-muted text-[13px]">v{strategy.version}</span>
          {strategy.bot_id && (
            <>
              <span className="text-text-muted text-[13px]">|</span>
              <span className="text-[13px]">
                실행 봇:{' '}
                <Link to={`/bots/${strategy.bot_id}`} className="text-text no-underline hover:underline">
                  {strategy.bot_id}
                </Link>
              </span>
            </>
          )}
        </div>
      </div>

      {/* 전략 개요: 2열 그리드 (전략 정보 + 전략 파라미터) */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* 전략 정보 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">전략 정보</h3>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">제출자</span>
            <span>
              {strategy.author ? (
                <>{strategy.author} {strategy.author_id && <span className="text-text-muted font-normal">{strategy.author_id}</span>}</>
              ) : '-'}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">버전</span>
            <span>{strategy.version}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">설명</span>
            <span className="text-[12px] text-text-muted">{strategy.description || '-'}</span>
          </div>
          {strategy.rationale && strategy.rationale.length > 0 && (
            <div className="mt-3">
              <div className="text-[12px] text-text-muted font-semibold mb-1">투자 근거</div>
              <div className="text-[12px] text-text-muted leading-relaxed whitespace-pre-line">{strategy.rationale}</div>
            </div>
          )}
          {strategy.risks && strategy.risks.length > 0 && (
            <div className="mt-3 pt-3 border-t border-border">
              <div className="text-[12px] text-text-muted font-semibold mb-1">리스크</div>
              <div className="text-[12px] text-text-muted leading-relaxed whitespace-pre-line">{strategy.risks}</div>
            </div>
          )}
        </div>

        {/* 전략 파라미터 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">전략 파라미터</h3>
          {strategy.params && Object.keys(strategy.params).length > 0 ? (
            <div className="space-y-0">
              {Object.entries(strategy.params).map(([key, raw]) => {
                const param = isStrategyParam(raw) ? raw : { value: raw }
                return (
                  <div key={key} className="flex justify-between py-2 border-b border-border text-[13px]">
                    <span className="text-text-muted">{key}</span>
                    <span>
                      <span className="font-mono">{String(param.value)}</span>
                      {param.description && (
                        <span className="text-text-muted text-[11px] ml-2">{param.description}</span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="py-4 text-text-muted text-[13px] text-center">파라미터가 없습니다</div>
          )}
        </div>
      </div>

      {/* 전략 성과 섹션 제목 */}
      <h3 className="text-[15px] font-semibold mb-4">전략 성과</h3>

      {/* 자산 추이 (Equity Curve) */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">자산 추이 (Equity Curve)</h3>
          <div className="flex gap-1 bg-bg rounded-lg p-0.5">
            {([['1w', '1주'], ['1m', '1개월'], ['3m', '3개월'], ['all', '전체']] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setEquityPeriod(key)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium border-none cursor-pointer ${equityPeriod === key ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <EquityCurveChart data={equityCurveData} className="h-[240px]" />
      </div>

      {/* 성과 지표 */}
      <PerformancePanel
        perf={performance}
        budgetAllocated={budgetAllocated}
        unrealizedPnl={unrealizedPnl}
      />

      {/* 2열 그리드: 기간별 성과 + 최근 거래 */}
      <div className="grid grid-cols-2 gap-4">
        {/* 좌: 기간별 성과 */}
        <div>
          <PeriodPerformance daily={dailySummary} weekly={weeklySummary} monthly={monthlySummary} strategyId={id} />
          <div className="mt-2 text-right">
            <Link to={`/strategies/${id}/performance`} className="text-[13px] text-primary no-underline hover:underline">
              기간별 성과 더보기 &rarr;
            </Link>
          </div>
        </div>

        {/* 우: 최근 거래 */}
        <div>
          <div className="bg-surface border border-border rounded-lg p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-semibold">최근 거래</h3>
              <Link to={`/strategies/${id}/trades`} className="text-[13px] text-primary no-underline hover:underline">
                전체 보기 &rarr;
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">시각</th>
                    <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">종목</th>
                    <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">매매</th>
                    <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">수량</th>
                    <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">단가</th>
                    <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">손익</th>
                  </tr>
                </thead>
                <tbody>
                  {(tradesData?.items ?? []).length === 0 ? (
                    <tr><td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">거래 내역이 없습니다</td></tr>
                  ) : (
                    (tradesData?.items ?? []).slice(0, 12).map((t) => (
                      <tr key={t.id} className="hover:bg-surface-hover">
                        <td className="px-3 py-2.5 border-b border-border text-[13px] font-mono text-text-muted">{formatShortDateTime(t.executed_at)}</td>
                        <td className="px-3 py-2.5 border-b border-border text-[13px]">{t.symbol}</td>
                        <td className="px-3 py-2.5 border-b border-border text-[13px]">
                          <StatusBadge variant={t.side === 'buy' ? 'negative' : 'positive'}>
                            {t.side === 'buy' ? '매수' : '매도'}
                          </StatusBadge>
                        </td>
                        <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatNumber(t.quantity)}</td>
                        <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatNumber(t.price)}</td>
                        <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                          {t.pnl != null ? (
                            <span className={t.pnl >= 0 ? 'text-positive' : 'text-negative'}>{formatNumber(t.pnl)}</span>
                          ) : (
                            <span className="text-text-muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

/** MM-DD HH:mm 형식의 짧은 날짜 시간 */
function formatShortDateTime(dateStr: string | undefined | null): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr.replace(' ', 'T'))
  if (isNaN(d.getTime())) return '-'
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${min}`
}

/** 전략 상태별 액션 버튼 */
function StatusActionButtons({
  status,
  hasRunningBot,
  isPending,
  onTransition,
}: {
  status: StrategyStatus
  hasRunningBot: boolean
  isPending: boolean
  onTransition: (newStatus: string) => void
}) {
  if (status === 'archived') return null

  if (status === 'active') {
    const disabled = hasRunningBot || isPending
    return (
      <div className="relative">
        <button
          disabled={disabled}
          onClick={() => onTransition('inactive')}
          className={`px-3 py-1.5 rounded-lg border text-[12px] font-medium ${
            disabled
              ? 'border-border text-text-muted cursor-not-allowed opacity-50'
              : 'border-warning text-warning cursor-pointer hover:bg-warning-bg'
          }`}
        >
          비활성화
        </button>
        {hasRunningBot && (
          <HintTooltip text="실행 중인 봇을 먼저 중지하세요" />
        )}
      </div>
    )
  }

  // registered or inactive -> archive
  return (
    <button
      disabled={isPending}
      onClick={() => onTransition('archived')}
      className="px-3 py-1.5 rounded-lg border border-border text-text-muted text-[12px] font-medium cursor-pointer hover:bg-surface-hover disabled:opacity-50 disabled:cursor-not-allowed"
    >
      보관
    </button>
  )
}
