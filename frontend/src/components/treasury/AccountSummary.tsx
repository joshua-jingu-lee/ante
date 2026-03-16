import { formatKRW, formatPercent } from '../../utils/formatters'
import type { TreasurySummary } from '../../types/treasury'

export default function AccountSummary({ summary }: { summary: TreasurySummary }) {
  const profitColor = summary.total_profit_loss >= 0 ? 'text-positive' : 'text-negative'
  const profitPercent = summary.total_evaluation > 0
    ? summary.total_profit_loss / (summary.total_evaluation - summary.total_profit_loss)
    : 0

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden mb-6">
      {/* KIS 헤더 */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="bg-primary text-white text-[11px] font-bold px-2 py-0.5 rounded">KIS</span>
          <span className="text-[14px] font-semibold">한국투자증권</span>
        </div>
        <div className="ml-auto flex items-center gap-4 text-[13px] text-text-muted">
          <span>수수료 {(summary.commission_rate * 100).toFixed(3)}%</span>
          <span>매도세 {(summary.sell_tax_rate * 100).toFixed(2)}%</span>
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
