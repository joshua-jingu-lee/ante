import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { BOT_STATUS_LABELS } from '../../utils/constants'
import type { Bot, BotStatus } from '../../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'muted', error: 'negative', deleted: 'muted',
}

interface BotTableProps {
  items: Bot[]
  onStart: (id: string) => void
  onStop: (id: string) => void
  onDelete: (id: string) => void
}

export default function BotTable({ items, onStart, onStop, onDelete }: BotTableProps) {
  const navigate = useNavigate()

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">ID</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">전략</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">상태</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">유형</th>
            <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border"></th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">등록된 봇이 없습니다</td></tr>
          ) : (
            items.map((bot) => (
              <tr key={bot.bot_id} onClick={() => navigate(`/bots/${bot.bot_id}`)} className="hover:bg-surface-hover cursor-pointer">
                <td className="px-3 py-3 border-b border-border text-[13px] font-mono font-medium">{bot.bot_id}</td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{bot.strategy_name || '-'}</td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  <StatusBadge variant={STATUS_VARIANT[bot.status] as 'positive'}>{BOT_STATUS_LABELS[bot.status] || bot.status}</StatusBadge>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  <StatusBadge variant={bot.mode === 'live' ? 'warning' : 'info'}>
                    {bot.mode === 'live' ? '실전' : '모의'}
                  </StatusBadge>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-right">
                  <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
                    {bot.status === 'stopped' || bot.status === 'created' ? (
                      <button onClick={() => onStart(bot.bot_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">시작</button>
                    ) : bot.status === 'running' ? (
                      <button onClick={() => onStop(bot.bot_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">중지</button>
                    ) : null}
                    <button onClick={() => onDelete(bot.bot_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-negative border border-border cursor-pointer hover:bg-negative-bg">삭제</button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
