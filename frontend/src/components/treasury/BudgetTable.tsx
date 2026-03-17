import { Link } from 'react-router-dom'
import { formatKRW, formatPercent } from '../../utils/formatters'
import type { BotBudget } from '../../types/treasury'

export default function BudgetTable({ budgets }: { budgets: BotBudget[] }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-4">Bot당 예산</h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Bot ID</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">배정예산</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">사용예산</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">잔여예산</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">체결대기</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">보유종목 평가금액</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">보유종목 손익</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">종목 수익률</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">예산 수익률</th>
            </tr>
          </thead>
          <tbody>
            {budgets.length === 0 ? (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-text-muted text-[13px]">할당된 봇이 없습니다</td></tr>
            ) : (
              budgets.map((b) => {
                const hasPosition = b.eval_amount != null
                const positionPnl = b.position_pnl ?? 0
                const pnlColor = positionPnl >= 0 ? 'text-positive' : 'text-negative'
                const budgetRoi = hasPosition && b.allocated > 0 ? positionPnl / b.allocated : 0
                const budgetRoiColor = budgetRoi >= 0 ? 'text-positive' : 'text-negative'
                return (
                  <tr key={b.bot_id} className="hover:bg-surface-hover">
                    <td className="px-3 py-3 border-b border-border text-[13px]">
                      <Link to={`/bots/${b.bot_id}`} className="text-primary no-underline hover:underline font-mono">{b.bot_id}</Link>
                    </td>
                    <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.allocated)}</td>
                    <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.spent)}</td>
                    <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.available)}</td>
                    <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.reserved)}</td>
                    <td className="px-3 py-3 border-b border-border text-[13px] text-right">{hasPosition ? formatKRW(b.eval_amount) : '-'}</td>
                    <td className={`px-3 py-3 border-b border-border text-[13px] text-right ${hasPosition ? pnlColor : ''}`}>{hasPosition ? formatKRW(positionPnl) : '-'}</td>
                    <td className={`px-3 py-3 border-b border-border text-[13px] text-right ${hasPosition ? pnlColor : ''}`}>{hasPosition ? formatPercent(b.position_return ?? 0) : '-'}</td>
                    <td className={`px-3 py-3 border-b border-border text-[13px] text-right ${hasPosition ? budgetRoiColor : ''}`}>{hasPosition ? formatPercent(budgetRoi) : '-'}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
