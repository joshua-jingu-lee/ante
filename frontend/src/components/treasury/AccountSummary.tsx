import { formatKRW, formatPercent } from '../../utils/formatters'
import type { TreasurySummary } from '../../types/treasury'

function formatSyncTime(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export default function AccountSummary({ summary }: { summary: TreasurySummary }) {
  const profitColor = summary.total_profit_loss >= 0 ? 'text-positive' : 'text-negative'
  const profitPercent = summary.total_evaluation > 0
    ? summary.total_profit_loss / (summary.total_evaluation - summary.total_profit_loss)
    : 0

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden mb-6">
      {/* 브로커 헤더 */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="bg-primary text-white text-[11px] font-bold px-2 py-0.5 rounded">{summary.broker_short_name || 'KIS'}</span>
          <span className="text-[14px] font-semibold">{summary.broker_name || '한국투자증권'}</span>
          {summary.exchange && (
            <span className="text-[11px] text-text-muted border border-border px-1.5 py-0.5 rounded">{summary.exchange}</span>
          )}
        </div>
        {summary.account_number && (
          <span className="text-[13px] font-mono">{summary.account_number}</span>
        )}
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${summary.is_demo_trading ? 'bg-warning-bg text-warning' : 'bg-positive-bg text-positive'}`}>
          {summary.is_demo_trading ? '모의투자' : '실전투자'}
        </span>
        <div className="ml-auto flex items-center gap-4 text-[13px] text-text-muted">
          <span>수수료 {(summary.commission_rate * 100).toFixed(3)}%</span>
          <span>매도세 {(summary.sell_tax_rate * 100).toFixed(2)}%</span>
          {summary.last_sync_time && (
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-positive inline-block" />
              동기화 {formatSyncTime(summary.last_sync_time)}
            </span>
          )}
        </div>
      </div>

      {/* 4개 통계 */}
      <div className="grid grid-cols-4">
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">총 자산 평가</div>
          <div className="text-[22px] font-bold">{formatKRW(summary.total_evaluation)}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">총 손익</div>
          <div className={`text-[22px] font-bold ${profitColor}`}>{formatKRW(summary.total_profit_loss)}</div>
          {profitPercent !== 0 && (
            <div className={`text-[13px] ${profitColor}`}>({formatPercent(profitPercent)})</div>
          )}
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">예수금</div>
          <div className="text-[22px] font-bold text-text-muted">{formatKRW(summary.account_balance)}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">매수가능금액</div>
          <div className="text-[22px] font-bold text-text-muted">{formatKRW(summary.purchasable_amount)}</div>
        </div>
      </div>
    </div>
  )
}
