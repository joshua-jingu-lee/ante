import { formatKRW, formatPercent } from '../../utils/formatters'
import type { TreasurySummary } from '../../types/treasury'

export default function AnteSummary({ summary }: { summary: TreasurySummary }) {
  const anteProfitColor = summary.ante_profit_loss >= 0 ? 'text-positive' : 'text-negative'
  const anteProfitPercent = summary.ante_purchase_amount > 0
    ? summary.ante_profit_loss / summary.ante_purchase_amount
    : 0

  const holdingPnl = summary.ante_eval_amount - summary.ante_purchase_amount
  const holdingProfitColor = holdingPnl >= 0 ? 'text-positive' : 'text-negative'
  const holdingProfitPercent = summary.ante_purchase_amount > 0
    ? holdingPnl / summary.ante_purchase_amount
    : 0

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden mb-6">
      {/* Ante 헤더 */}
      <div className="flex items-center gap-4 px-5 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="bg-positive text-white text-[11px] font-bold px-2 py-0.5 rounded">Ante</span>
          <span className="text-[14px] font-semibold">관리 자금</span>
        </div>
        <span className="text-[13px] text-text-muted">Bot {summary.bot_count}개 운용 중</span>
        {summary.budget_exceeds_purchasable && (
          <div className="ml-auto flex items-center gap-1.5 bg-warning-bg text-warning px-3 py-1 rounded text-[12px]">
            ⚠ 잔여예산이 매수가능금액을 초과합니다
          </div>
        )}
      </div>

      {/* 상단 4개 */}
      <div className="grid grid-cols-4 border-b border-border">
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">Ante 관리자산 평가</div>
          <div className="text-[22px] font-bold">{formatKRW(summary.ante_eval_amount)}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">Ante 관리자산 손익</div>
          <div className={`text-[22px] font-bold ${anteProfitColor}`}>{formatKRW(summary.ante_profit_loss)}</div>
          {anteProfitPercent !== 0 && (
            <div className={`text-[13px] ${anteProfitColor}`}>({formatPercent(anteProfitPercent)})</div>
          )}
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">Bot 배정예산</div>
          <div className="text-[22px] font-bold text-text-muted">{formatKRW(summary.total_allocated)}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">잔여예산</div>
          <div className="text-[22px] font-bold text-text-muted">{formatKRW(summary.total_available)}</div>
        </div>
      </div>

      {/* 하단 3개 */}
      <div className="grid grid-cols-4">
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">보유종목 평가금액</div>
          <div className="text-[22px] font-bold">{formatKRW(summary.ante_eval_amount)}</div>
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">보유종목 손익</div>
          <div className={`text-[22px] font-bold ${holdingProfitColor}`}>{formatKRW(holdingPnl)}</div>
          {holdingProfitPercent !== 0 && (
            <div className={`text-[13px] ${holdingProfitColor}`}>({formatPercent(holdingProfitPercent)})</div>
          )}
        </div>
        <div className="px-5 py-4">
          <div className="text-[12px] text-text-muted mb-1">체결대기 자금</div>
          <div className="text-[22px] font-bold text-text-muted">{formatKRW(summary.total_reserved)}</div>
        </div>
      </div>
    </div>
  )
}
