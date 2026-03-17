import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useStrategyDetail, useStrategyPerformance, useStrategyTrades, useStrategyDailySummary, useStrategyMonthlySummary } from '../hooks/useStrategies'
import PerformancePanel from '../components/strategies/PerformancePanel'
import PeriodPerformance from '../components/strategies/PeriodPerformance'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatKRW, formatDateTime } from '../utils/formatters'
import { STRATEGY_STATUS_LABELS } from '../utils/constants'
import type { StrategyStatus } from '../types/strategy'

const STATUS_VARIANT: Record<StrategyStatus, string> = {
  active: 'positive', registered: 'info', inactive: 'muted', archived: 'muted',
}

type EquityCurvePeriod = '1w' | '1m' | '3m' | 'all'

export default function StrategyDetail() {
  const { id = '' } = useParams<{ id: string }>()
  const [equityPeriod, setEquityPeriod] = useState<EquityCurvePeriod>('all')

  const { data: strategy, isLoading } = useStrategyDetail(id)
  const { data: performance } = useStrategyPerformance(id)
  const { data: tradesData } = useStrategyTrades(id)
  const { data: dailySummary } = useStrategyDailySummary(id)
  const { data: monthlySummary } = useStrategyMonthlySummary(id)

  if (isLoading) return <PageSkeleton />
  if (!strategy) return <div className="text-text-muted text-center py-12">전략을 찾을 수 없습니다</div>

  return (
    <>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[20px] font-bold">{strategy.name}</h2>
          <div className="flex gap-3 items-center mt-1">
            <span className="text-text-muted text-[13px]">v{strategy.version}</span>
            <StatusBadge variant={STATUS_VARIANT[strategy.status] as 'positive'}>
              {STRATEGY_STATUS_LABELS[strategy.status]}
            </StatusBadge>
            {strategy.bot_id && (
              <span className="text-[13px] text-text-muted">
                실행 봇:{' '}
                <Link to={`/bots/${strategy.bot_id}`} className="text-primary no-underline hover:underline">
                  {strategy.bot_id}
                </Link>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 전략 정보 카드 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">전략 정보</h3>
        <div className="space-y-2">
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">제출자</span>
            <span>{strategy.author || '-'}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">버전</span>
            <span>v{strategy.version}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">설명</span>
            <span>{strategy.description || '-'}</span>
          </div>
          {strategy.params && Object.keys(strategy.params).length > 0 && (
            <div className="pt-2 text-[13px]">
              <span className="text-text-muted block mb-2">파라미터</span>
              <div className="bg-bg rounded-lg p-3 space-y-1">
                {Object.entries(strategy.params).map(([key, value]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-text-muted font-mono text-[12px]">{key}</span>
                    <span className="text-[12px]">{String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 에쿼티 커브 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">자산 추이</h3>
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
        {!performance || performance.total_trades === 0 ? (
          <div className="py-8 text-center text-text-muted text-[13px]">
            아직 자산 추이 데이터가 없습니다
          </div>
        ) : (
          <div className="h-[280px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
            에쿼티 커브 (TradingView Area Chart)
          </div>
        )}
      </div>

      {/* 성과 지표 */}
      <PerformancePanel perf={performance} />

      {/* 2열 그리드: 기간별 성과 + 최근 거래 */}
      <div className="grid grid-cols-2 gap-6">
        {/* 좌: 기간별 성과 */}
        <PeriodPerformance daily={dailySummary} monthly={monthlySummary} />

        {/* 우: 최근 거래 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">최근 거래</h3>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">종목</th>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">방향</th>
                  <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">가격</th>
                  <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">손익</th>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">체결일</th>
                </tr>
              </thead>
              <tbody>
                {(tradesData?.items ?? []).length === 0 ? (
                  <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">거래 내역이 없습니다</td></tr>
                ) : (
                  (tradesData?.items ?? []).slice(0, 10).map((t) => (
                    <tr key={t.id} className="hover:bg-surface-hover">
                      <td className="px-3 py-2.5 border-b border-border text-[13px] font-mono">{t.symbol}</td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px]">
                        <StatusBadge variant={t.side === 'buy' ? 'positive' : 'negative'}>
                          {t.side === 'buy' ? '매수' : '매도'}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">{formatKRW(t.price)}</td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                        {t.pnl != null ? (
                          <span className={t.pnl >= 0 ? 'text-positive' : 'text-negative'}>{formatKRW(t.pnl)}</span>
                        ) : '-'}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-text-muted">{formatDateTime(t.executed_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}
