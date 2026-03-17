import { useState } from 'react'
import { useBots, useBotControl } from '../hooks/useBots'
import BotCard from '../components/bots/BotCard'
import BotCreateForm from '../components/bots/BotCreateForm'
import BotStopModal from '../components/bots/BotStopModal'
import BotDeleteModal from '../components/bots/BotDeleteModal'
import { TableSkeleton } from '../components/common/Skeleton'
import type { Bot } from '../types/bot'

export default function Bots() {
  const [showCreate, setShowCreate] = useState(false)
  const [stopTarget, setStopTarget] = useState<Bot | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Bot | null>(null)
  const { data, isLoading } = useBots()
  const { start, stop, remove } = useBotControl()

  const allBots = data?.items ?? []
  const runningBots = allBots.filter((b) => b.status === 'running')
  const inactiveBots = allBots.filter((b) => b.status !== 'running' && b.status !== 'deleted')

  const handleStopClick = (id: string) => {
    const bot = allBots.find((b) => b.bot_id === id)
    if (bot) setStopTarget(bot)
  }

  const handleDeleteClick = (id: string) => {
    const bot = allBots.find((b) => b.bot_id === id)
    if (bot) setDeleteTarget(bot)
  }

  const handleStopConfirm = () => {
    if (stopTarget) {
      stop.mutate(stopTarget.bot_id, { onSuccess: () => setStopTarget(null) })
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteTarget) {
      remove.mutate(deleteTarget.bot_id, { onSuccess: () => setDeleteTarget(null) })
    }
  }

  return (
    <>
      {isLoading ? (
        <TableSkeleton rows={3} cols={3} />
      ) : (
        <>
          {/* 실행 중 섹션 */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted">
              실행 중
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{runningBots.length}</span>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
            >
              봇 생성
            </button>
          </div>

          <div className="mb-8">
            {runningBots.length === 0 ? (
              <div className="text-[13px] text-text-muted py-8 text-center">실행 중인 봇이 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {runningBots.map((bot) => (
                  <BotCard key={bot.bot_id} bot={bot} onStart={(id) => start.mutate(id)} onStop={handleStopClick} onDelete={handleDeleteClick} />
                ))}
              </div>
            )}
          </div>

          {/* 비활성 섹션 */}
          <div className="mb-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted">
              비활성
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{inactiveBots.length}</span>
            </div>
          </div>

          <div className="mb-8">
            {inactiveBots.length === 0 ? (
              <div className="text-[13px] text-text-muted py-8 text-center">비활성 봇이 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {inactiveBots.map((bot) => (
                  <BotCard key={bot.bot_id} bot={bot} onStart={(id) => start.mutate(id)} onStop={handleStopClick} onDelete={handleDeleteClick} />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {showCreate && <BotCreateForm onClose={() => setShowCreate(false)} />}

      {stopTarget && (
        <BotStopModal
          bot={stopTarget}
          onConfirm={handleStopConfirm}
          onClose={() => setStopTarget(null)}
          isPending={stop.isPending}
        />
      )}

      {deleteTarget && (
        <BotDeleteModal
          bot={deleteTarget}
          onConfirm={handleDeleteConfirm}
          onClose={() => setDeleteTarget(null)}
          isPending={remove.isPending}
        />
      )}
    </>
  )
}
