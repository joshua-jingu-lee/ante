import { useParams, Link } from 'react-router-dom'
import { useBotDetail, useBotControl } from '../hooks/useBots'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatKRW, formatDateTime } from '../utils/formatters'
import { BOT_STATUS_LABELS } from '../utils/constants'
import type { BotStatus } from '../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'muted', error: 'negative', deleted: 'muted',
}

export default function BotDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: bot, isLoading } = useBotDetail(id!)
  const { start, stop } = useBotControl()

  if (isLoading) return <PageSkeleton />
  if (!bot) return <div className="text-text-muted text-center py-12">봇을 찾을 수 없습니다</div>

  const canStart = bot.status === 'stopped' || bot.status === 'created'
  const canStop = bot.status === 'running'

  return (
    <>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[20px] font-bold">
            {bot.name || bot.bot_id}
            {bot.name && <span className="ml-2 text-[14px] font-normal text-text-muted font-mono">{bot.bot_id}</span>}
          </h2>
          <div className="flex gap-3 items-center mt-1">
            <StatusBadge variant={STATUS_VARIANT[bot.status] as 'positive'}>
              {BOT_STATUS_LABELS[bot.status]}
            </StatusBadge>
            <StatusBadge variant={bot.mode === 'live' ? 'warning' : 'info'}>
              {bot.mode === 'live' ? '실전' : '모의'}
            </StatusBadge>
            {bot.strategy_name && (
              <Link to="/strategies" className="text-primary text-[13px] no-underline hover:underline">
                {bot.strategy_name}
              </Link>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {canStart && (
            <button onClick={() => start.mutate(bot.bot_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">시작</button>
          )}
          {canStop && (
            <button onClick={() => stop.mutate(bot.bot_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">중지</button>
          )}
        </div>
      </div>

      {/* 설정 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">실행 설정</h3>
        <div className="space-y-2">
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">실행 간격</span>
            <span>{bot.interval_seconds}초</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">대상 종목</span>
            <span className="font-mono">{bot.symbols?.length ? bot.symbols.join(', ') : '-'}</span>
          </div>
          <div className="flex justify-between py-2 text-[13px]">
            <span className="text-text-muted">할당 예산</span>
            <span>{formatKRW(bot.allocated_budget)}</span>
          </div>
        </div>
      </div>

      {/* 실행 로그 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-3">실행 로그</h3>
        {(bot.logs ?? []).length === 0 ? (
          <div className="py-4 text-text-muted text-[13px] text-center">로그가 없습니다</div>
        ) : (
          <div className="space-y-0">
            {bot.logs.map((log, i) => (
              <div key={i} className="flex gap-3 py-2 border-b border-border text-[13px]">
                <span className="text-text-muted font-mono text-[12px] whitespace-nowrap">{formatDateTime(log.timestamp)}</span>
                <StatusBadge variant={log.success ? 'positive' : 'negative'}>
                  {log.success ? '성공' : '실패'}
                </StatusBadge>
                {log.message && <span className="text-text-muted">{log.message}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
