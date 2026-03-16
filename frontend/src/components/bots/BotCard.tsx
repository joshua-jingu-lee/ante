import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { BOT_STATUS_LABELS } from '../../utils/constants'
import type { Bot, BotStatus } from '../../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'muted', error: 'negative', deleted: 'muted',
}

interface BotCardProps {
  bot: Bot
  onStart: (id: string) => void
  onStop: (id: string) => void
  onDelete: (id: string) => void
}

function BotIcon({ status }: { status: BotStatus }) {
  const bgClass = status === 'running'
    ? 'bg-positive-bg text-positive'
    : status === 'error'
      ? 'bg-negative-bg text-negative'
      : 'bg-bg text-text-muted'

  return (
    <div className={`w-[72px] h-[72px] rounded-full flex items-center justify-center shrink-0 ${bgClass}`}>
      <svg viewBox="0 0 24 24" className="w-12 h-12 fill-current">
        <circle cx="12" cy="2" r="1.5" />
        <line x1="12" y1="3.5" x2="12" y2="6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <rect x="4" y="6" width="16" height="12" rx="3" ry="3" />
        <circle cx="9" cy="12" r="2" className="fill-surface" />
        <circle cx="15" cy="12" r="2" className="fill-surface" />
        <rect x="8" y="20" width="3" height="3" rx="1" />
        <rect x="13" y="20" width="3" height="3" rx="1" />
      </svg>
    </div>
  )
}

export default function BotCard({ bot, onStart, onStop, onDelete }: BotCardProps) {
  const navigate = useNavigate()

  return (
    <div className="bg-surface border border-border rounded-lg p-5 flex gap-4 items-start">
      <BotIcon status={bot.status} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[15px] font-semibold">{bot.name || bot.bot_id}</span>
          <StatusBadge variant={STATUS_VARIANT[bot.status] as 'positive'}>{BOT_STATUS_LABELS[bot.status] || bot.status}</StatusBadge>
        </div>
        <div className="text-[13px] text-text-muted mb-3">
          <a onClick={() => navigate(`/bots/${bot.bot_id}`)} className="hover:text-primary cursor-pointer">{bot.bot_id}</a>
        </div>
        <div className="flex flex-col gap-1.5 text-[13px] text-text-muted mb-4">
          <div className="flex justify-between">
            <span>전략</span>
            <span>{bot.strategy_name ? <a onClick={() => navigate(`/strategies/${bot.strategy_name}`)} className="text-primary hover:underline cursor-pointer">{bot.strategy_name}</a> : '-'}</span>
          </div>
          <div className="flex justify-between">
            <span>모드</span>
            <StatusBadge variant={bot.mode === 'live' ? 'warning' : 'info'}>{bot.mode === 'live' ? '실전' : '모의'}</StatusBadge>
          </div>
        </div>
        <div className="flex gap-2 justify-end">
          {(bot.status === 'stopped' || bot.status === 'created') && (
            <>
              <button onClick={() => onStart(bot.bot_id)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">시작</button>
              <button onClick={() => onDelete(bot.bot_id)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-negative border-none cursor-pointer hover:underline">삭제</button>
            </>
          )}
          {bot.status === 'running' && (
            <button onClick={() => onStop(bot.bot_id)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-negative border border-negative cursor-pointer hover:bg-negative-bg">중지</button>
          )}
          {bot.status === 'error' && (
            <button onClick={() => onDelete(bot.bot_id)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-negative border-none cursor-pointer hover:underline">삭제</button>
          )}
        </div>
      </div>
    </div>
  )
}
