import { useState } from 'react'
import { useBots, useBotControl } from '../hooks/useBots'
import BotTable from '../components/bots/BotTable'
import BotCreateForm from '../components/bots/BotCreateForm'
import { TableSkeleton } from '../components/common/Skeleton'
import type { BotStatus } from '../types/bot'

const STATUS_FILTERS: { key: BotStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'running', label: '실행 중' },
  { key: 'stopped', label: '중지됨' },
  { key: 'error', label: '오류' },
]

export default function Bots() {
  const [statusFilter, setStatusFilter] = useState<BotStatus | 'all'>('all')
  const [showCreate, setShowCreate] = useState(false)
  const { data, isLoading } = useBots()
  const { start, stop, remove } = useBotControl()

  const items = (data?.items ?? []).filter(
    (b) => statusFilter === 'all' || b.status === statusFilter,
  )

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
                statusFilter === f.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
        >
          봇 생성
        </button>
      </div>

      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : (
          <BotTable
            items={items}
            onStart={(id) => start.mutate(id)}
            onStop={(id) => stop.mutate(id)}
            onDelete={(id) => { if (confirm('이 봇을 삭제하시겠습니까?')) remove.mutate(id) }}
          />
        )}
      </div>

      {showCreate && <BotCreateForm onClose={() => setShowCreate(false)} />}
    </>
  )
}
