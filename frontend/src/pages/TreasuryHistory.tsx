import { useState } from 'react'
import { useTreasuryTransactions, useBotBudgets } from '../hooks/useTreasury'
import { formatKRW, formatDateTime } from '../utils/formatters'
import { TRANSACTION_TYPE_LABELS, TRANSACTION_TYPE_VARIANT } from '../utils/constants'
import StatusBadge from '../components/common/StatusBadge'
import Pagination from '../components/common/Pagination'
import { TableSkeleton } from '../components/common/Skeleton'

const LIMIT = 20
const TYPE_TABS = [
  { value: '', label: '전체' },
  { value: 'allocate', label: '할당' },
  { value: 'deallocate', label: '회수' },
  { value: 'fill', label: '체결' },
]

export default function TreasuryHistory() {
  const [typeFilter, setTypeFilter] = useState('')
  const [botFilter, setBotFilter] = useState('')
  const [offset, setOffset] = useState(0)

  const { data: budgets } = useBotBudgets()
  const botIds = (budgets ?? []).map((b) => b.bot_id)

  const { data, isLoading } = useTreasuryTransactions({
    offset,
    limit: LIMIT,
    type: typeFilter || undefined,
    bot_id: botFilter || undefined,
  })

  const handleTypeChange = (t: string) => { setTypeFilter(t); setOffset(0) }
  const handleBotChange = (b: string) => { setBotFilter(b); setOffset(0) }

  return (
    <>
      {/* 필터 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1">
          {TYPE_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => handleTypeChange(tab.value)}
              className={`px-3 py-1.5 rounded-lg text-[13px] font-medium border-none cursor-pointer transition-colors ${
                typeFilter === tab.value
                  ? 'bg-primary text-white'
                  : 'bg-transparent text-text-muted hover:bg-surface-hover hover:text-text'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <select
          value={botFilter}
          onChange={(e) => handleBotChange(e.target.value)}
          className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] cursor-pointer"
        >
          <option value="">전체 Bot</option>
          {botIds.map((id) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
      </div>

      {/* 이력 테이블 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : (
          <>
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
                  {(data?.items ?? []).length === 0 ? (
                    <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">이력이 없습니다</td></tr>
                  ) : (
                    (data?.items ?? []).map((tx) => (
                      <tr key={tx.id} className="hover:bg-surface-hover">
                        <td className="px-3 py-3 border-b border-border text-[13px] font-mono text-text-muted">{formatDateTime(tx.created_at)}</td>
                        <td className="px-3 py-3 border-b border-border text-[13px]">
                          <StatusBadge variant={TRANSACTION_TYPE_VARIANT[tx.type] ?? 'muted'}>
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
            {(data?.total ?? 0) > LIMIT && (
              <Pagination total={data?.total ?? 0} offset={offset} limit={LIMIT} onPageChange={setOffset} />
            )}
          </>
        )}
      </div>
    </>
  )
}
