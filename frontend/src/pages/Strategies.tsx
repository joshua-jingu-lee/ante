import { useState } from 'react'
import { useStrategies } from '../hooks/useStrategies'
import StrategyTable from '../components/strategies/StrategyTable'
import Pagination from '../components/common/Pagination'
import { TableSkeleton } from '../components/common/Skeleton'
import type { StrategyStatus } from '../types/strategy'

const STATUS_FILTERS: { key: StrategyStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'active', label: '운용중' },
  { key: 'registered', label: '대기' },
  { key: 'inactive', label: '중지' },
]

const PAGE_SIZE = 5

export default function Strategies() {
  const [statusFilter, setStatusFilter] = useState<StrategyStatus | 'all'>('all')
  const [offset, setOffset] = useState(0)
  const { data: strategies, isLoading } = useStrategies()

  const filtered = (strategies ?? []).filter(
    (s) => statusFilter === 'all' || s.status === statusFilter,
  )

  const paged = filtered.slice(offset, offset + PAGE_SIZE)

  const handleFilterChange = (key: StrategyStatus | 'all') => {
    setStatusFilter(key)
    setOffset(0)
  }

  return (
    <>
      <div className="flex gap-1 bg-bg rounded-lg p-0.5 mb-4 w-fit">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => handleFilterChange(f.key)}
            className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
              statusFilter === f.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <TableSkeleton rows={5} cols={6} />
        ) : (
          <>
            <StrategyTable items={paged} />
            {filtered.length > PAGE_SIZE && (
              <Pagination total={filtered.length} offset={offset} limit={PAGE_SIZE} onPageChange={setOffset} />
            )}
          </>
        )}
      </div>
    </>
  )
}
