import { Link } from 'react-router-dom'
import { useTreasuryTransactions } from '../../hooks/useTreasury'
import { formatKRW, formatDateTime } from '../../utils/formatters'
import { TRANSACTION_TYPE_LABELS, TRANSACTION_TYPE_VARIANT } from '../../utils/constants'
import StatusBadge from '../common/StatusBadge'

export default function RecentTransactions() {
  const { data } = useTreasuryTransactions({ limit: 5 })
  const items = data?.items ?? []

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-semibold">최근 자금 변동</h3>
        <Link to="/treasury/history" className="text-[13px] text-primary no-underline hover:underline">전체 보기 →</Link>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">시각</th>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">유형</th>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Bot</th>
              <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">금액</th>
              <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">비고</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">변동 이력이 없습니다</td></tr>
            ) : (
              items.map((tx) => (
                <tr key={tx.id} className="hover:bg-surface-hover">
                  <td className="px-3 py-3 border-b border-border text-[13px] font-mono text-text-muted">{formatDateTime(tx.created_at)}</td>
                  <td className="px-3 py-3 border-b border-border text-[13px]">
                    <StatusBadge variant={TRANSACTION_TYPE_VARIANT[tx.type] ?? 'default'}>
                      {TRANSACTION_TYPE_LABELS[tx.type] ?? tx.type}
                    </StatusBadge>
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px] font-mono">{tx.bot_id || '-'}</td>
                  <td className={`px-3 py-3 border-b border-border text-[13px] text-right ${tx.type === 'allocate' ? 'text-positive' : tx.type === 'deallocate' ? 'text-negative' : ''}`}>
                    {tx.type === 'allocate' ? '+' : ''}{formatKRW(tx.amount)}
                  </td>
                  <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{tx.description}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
