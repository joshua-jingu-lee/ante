import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatPercent } from '../../utils/formatters'
import { STRATEGY_STATUS_LABELS } from '../../utils/constants'
import type { Strategy, StrategyStatus } from '../../types/strategy'

const STATUS_VARIANT: Record<StrategyStatus, string> = {
  active: 'positive',
  registered: 'info',
  inactive: 'muted',
  archived: 'muted',
}

export default function StrategyTable({ items }: { items: Strategy[] }) {
  const navigate = useNavigate()

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">전략명</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">버전</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">제출자</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">상태</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">실행 봇</th>
            <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">누적 수익률</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">등록된 전략이 없습니다</td></tr>
          ) : (
            items.map((s) => (
              <tr key={s.id} onClick={() => navigate(`/strategies/${s.id}`)} className="hover:bg-surface-hover cursor-pointer">
                <td className="px-3 py-3 border-b border-border text-[13px] font-medium">{s.name}</td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{s.version}</td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{s.author || '-'}</td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  <StatusBadge variant={STATUS_VARIANT[s.status] as 'positive'}>{STRATEGY_STATUS_LABELS[s.status] || s.status}</StatusBadge>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] font-mono text-text-muted">{s.bot_id || '-'}</td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-right">
                  {s.cumulative_return != null ? (
                    <span className={s.cumulative_return >= 0 ? 'text-positive' : 'text-negative'}>
                      {formatPercent(s.cumulative_return / 100)}
                    </span>
                  ) : '-'}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
