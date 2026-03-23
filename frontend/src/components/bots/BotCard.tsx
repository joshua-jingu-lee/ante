import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { BOT_STATUS_LABELS } from '../../utils/constants'
import type { Bot, BotStatus } from '../../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'muted', error: 'negative', deleted: 'muted',
}

interface BotCardProps {
  bot: Bot
}

function BotIcon({ status }: { status: BotStatus }) {
  const isRunning = status === 'running'
  const bgClass = isRunning
    ? 'bg-positive-bg text-positive'
    : status === 'error'
      ? 'bg-negative-bg text-negative'
      : 'bg-bg text-text-muted'

  return (
    <div
      className={`w-[72px] h-[72px] rounded-full flex items-center justify-center shrink-0 ${bgClass}`}
      style={isRunning ? { animation: 'border-glow 1.5s ease-in-out infinite' } : undefined}
    >
      <svg viewBox="0 0 24 24" className="w-12 h-12 fill-current">
        <circle
          cx="12" cy="2" r="1.5"
          style={isRunning ? { animation: 'antenna-pulse 1.2s ease-in-out infinite', fill: '#fff' } : undefined}
        />
        <line
          x1="12" y1="3.5" x2="12" y2="6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
          style={isRunning ? { animation: 'antenna-pulse 1.2s ease-in-out infinite' } : undefined}
        />
        <rect x="4" y="6" width="16" height="12" rx="3" ry="3" />
        <circle
          cx="9" cy="12" r="2"
          className={isRunning ? '' : 'fill-surface'}
          style={isRunning ? { animation: 'eye-glow 1.5s ease-in-out infinite' } : undefined}
        />
        <circle
          cx="15" cy="12" r="2"
          className={isRunning ? '' : 'fill-surface'}
          style={isRunning ? { animation: 'eye-glow 1.5s ease-in-out infinite' } : undefined}
        />
        <rect x="8" y="20" width="3" height="3" rx="1" />
        <rect x="13" y="20" width="3" height="3" rx="1" />
      </svg>
    </div>
  )
}

export default function BotCard({ bot }: BotCardProps) {
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
        <div className="flex flex-col gap-1.5 text-[13px] text-text-muted">
          <div className="flex justify-between">
            <span>전략</span>
            <span>{bot.strategy_name ? <a onClick={() => navigate(`/strategies/${bot.strategy_name}`)} className="text-primary hover:underline cursor-pointer">{bot.strategy_name}</a> : '-'}</span>
          </div>
          {bot.interval_seconds != null && (
            <div className="flex justify-between">
              <span>실행 간격</span>
              <span>{bot.interval_seconds}초</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
