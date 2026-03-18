import { Link } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatPercent } from '../../utils/formatters'
import { STRATEGY_STATUS_LABELS } from '../../utils/constants'
import type { Strategy, StrategyStatus } from '../../types/strategy'

const STATUS_VARIANT: Record<StrategyStatus, string> = {
  active: 'positive',
  registered: 'warning',
  inactive: 'muted',
  archived: 'muted',
}

export default function StrategyTable({ items }: { items: Strategy[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">전략명</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">버전</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">제출자</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">상태</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">실행 봇</th>
            <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted border-b border-border">누적 수익률</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">등록된 전략이 없습니다</td></tr>
          ) : (
            items.map((s) => (
              <tr key={s.id} className="hover:bg-surface-hover">
                <td className="px-3 py-3 border-b border-border text-[13px] font-medium">
                  <Link to={`/strategies/${s.id}`} className="text-text no-underline hover:underline">{s.name}</Link>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">v{s.version}</td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  {s.author ? (
                    <span>{s.author} {s.author_id && <span className="text-text-muted font-normal">{s.author_id}</span>}</span>
                  ) : (
                    <span className="text-text-muted">-</span>
                  )}
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  <StatusBadge variant={STATUS_VARIANT[s.status] as 'positive'}>{STRATEGY_STATUS_LABELS[s.status] || s.status}</StatusBadge>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  {s.bot_id ? (
                    <Link to={`/bots/${s.bot_id}`} className="text-text font-mono no-underline hover:underline">{s.bot_id}</Link>
                  ) : (
                    <span className="text-text-muted">-</span>
                  )}
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-right">
                  {s.cumulative_return != null ? (
                    <span className={`font-bold ${s.cumulative_return >= 0 ? 'text-positive' : 'text-negative'}`}>
                      {formatPercent(s.cumulative_return / 100)}
                    </span>
                  ) : (
                    <span className="text-text-muted">-</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
