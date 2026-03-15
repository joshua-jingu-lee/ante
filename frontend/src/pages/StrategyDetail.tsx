import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useStrategyDetail, useStrategyPerformance, useStrategyTrades } from '../hooks/useStrategies'
import PerformancePanel from '../components/strategies/PerformancePanel'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import { formatKRW, formatDateTime } from '../utils/formatters'
import { STRATEGY_STATUS_LABELS } from '../utils/constants'
import type { StrategyStatus } from '../types/strategy'

const STATUS_VARIANT: Record<StrategyStatus, string> = {
  active: 'positive', registered: 'info', inactive: 'muted', archived: 'muted',
}

type Tab = 'performance' | 'trades'

export default function StrategyDetail() {
  const { id } = useParams<{ id: string }>()
  const numId = Number(id)
  const [tab, setTab] = useState<Tab>('performance')

  const { data: strategy, isLoading } = useStrategyDetail(numId)
  const { data: performance } = useStrategyPerformance(numId)
  const { data: tradesData } = useStrategyTrades(numId)

  if (isLoading) return <LoadingSpinner />
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
              <Link to={`/bots/${strategy.bot_id}`} className="text-primary text-[13px] no-underline hover:underline">
                {strategy.bot_id}
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* 에쿼티 커브 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">자산 추이</h3>
        <div className="h-[280px] bg-bg border border-dashed border-border rounded-lg flex items-center justify-center text-text-muted text-[13px]">
          📈 에쿼티 커브 (TradingView Area Chart)
        </div>
      </div>

      {/* 성과 지표 */}
      {performance && <PerformancePanel perf={performance} />}

      {/* 탭 */}
      <div className="flex gap-1 bg-bg rounded-lg p-0.5 mb-4 w-fit">
        <button
          onClick={() => setTab('performance')}
          className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${tab === 'performance' ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}
        >
          파라미터
        </button>
        <button
          onClick={() => setTab('trades')}
          className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${tab === 'trades' ? 'bg-surface text-text' : 'bg-transparent text-text-muted'}`}
        >
          거래 내역
        </button>
      </div>

      {tab === 'performance' && strategy.params && (
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">전략 파라미터</h3>
          <div className="space-y-2">
            {Object.entries(strategy.params).map(([key, value]) => (
              <div key={key} className="flex justify-between py-2 border-b border-border text-[13px]">
                <span className="text-text-muted font-mono">{key}</span>
                <span>{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'trades' && (
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">거래 내역</h3>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">종목</th>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">방향</th>
                  <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">수량</th>
                  <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">가격</th>
                  <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">손익</th>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">체결일</th>
                </tr>
              </thead>
              <tbody>
                {(tradesData?.items ?? []).length === 0 ? (
                  <tr><td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">거래 내역이 없습니다</td></tr>
                ) : (
                  (tradesData?.items ?? []).map((t) => (
                    <tr key={t.id} className="hover:bg-surface-hover">
                      <td className="px-3 py-3 border-b border-border text-[13px] font-mono">{t.symbol}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px]">
                        <StatusBadge variant={t.side === 'buy' ? 'positive' : 'negative'}>
                          {t.side === 'buy' ? '매수' : '매도'}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-right">{t.quantity}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(t.price)}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-right">
                        {t.pnl != null ? (
                          <span className={t.pnl >= 0 ? 'text-positive' : 'text-negative'}>{formatKRW(t.pnl)}</span>
                        ) : '-'}
                      </td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{formatDateTime(t.executed_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
