import { formatKRW } from '../../utils/formatters'
import type { BotBudget } from '../../types/treasury'

export default function BudgetTable({ budgets }: { budgets: BotBudget[] }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-4">봇별 예산</h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">봇 ID</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">할당액</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">가용액</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">예약액</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">사용액</th>
            </tr>
          </thead>
          <tbody>
            {budgets.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">할당된 봇이 없습니다</td></tr>
            ) : (
              budgets.map((b) => (
                <tr key={b.bot_id} className="hover:bg-surface-hover">
                  <td className="px-3 py-3 border-b border-border text-[13px] font-mono">{b.bot_id}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.allocated)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.available)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.reserved)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(b.used)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
