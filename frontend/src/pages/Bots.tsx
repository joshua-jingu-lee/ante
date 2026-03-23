import { useState } from 'react'
import { useBots } from '../hooks/useBots'
import BotCard from '../components/bots/BotCard'
import BotCreateForm from '../components/bots/BotCreateForm'
import VirtualModeBanner from '../components/common/VirtualModeBanner'
import { TableSkeleton } from '../components/common/Skeleton'
import type { BotStatus } from '../types/bot'

const STATUS_ORDER: Record<BotStatus, number> = {
  running: 0,
  stopped: 1,
  error: 2,
  created: 3,
  stopping: 4,
  deleted: 5,
}

export default function Bots() {
  const [showCreate, setShowCreate] = useState(false)
  const { data, isLoading } = useBots()

  const allBots = [...(data?.items ?? [])]
    .filter((b) => b.status !== 'deleted')
    .sort((a, b) => (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99))

  const isVirtual = allBots.length > 0 && allBots.every((b) => b.mode === 'paper')

  return (
    <>
      {isLoading ? (
        <TableSkeleton rows={3} cols={3} />
      ) : (
        <>
          <VirtualModeBanner isVirtual={isVirtual} />

          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted">
              봇 관리
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{allBots.length}</span>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
            >
              + 봇 생성
            </button>
          </div>

          <div className="mb-8">
            {allBots.length === 0 ? (
              <div className="text-[13px] text-text-muted py-8 text-center">등록된 봇이 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {allBots.map((bot) => (
                  <BotCard key={bot.bot_id} bot={bot} />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {showCreate && <BotCreateForm onClose={() => setShowCreate(false)} />}
    </>
  )
}
