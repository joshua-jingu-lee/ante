import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useBotDetail, useBotControl } from '../hooks/useBots'
import { useStrategies } from '../hooks/useStrategies'
import { useTreasurySummary } from '../hooks/useTreasury'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatKRW, formatDateTime } from '../utils/formatters'
import { BOT_STATUS_LABELS } from '../utils/constants'
import type { BotStatus, BotMode, BotDetail as BotDetailType } from '../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'warning', error: 'negative', deleted: 'muted',
}

export default function BotDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: bot, isLoading } = useBotDetail(id!)
  const { start, stop } = useBotControl()
  const [showEditModal, setShowEditModal] = useState(false)

  if (isLoading) return <PageSkeleton />
  if (!bot) return <div className="text-text-muted text-center py-12">봇을 찾을 수 없습니다</div>

  const canStart = bot.status === 'stopped' || bot.status === 'created'
  const canStop = bot.status === 'running'
  const canEdit = bot.status === 'stopped' || bot.status === 'created'
  const isStopped = bot.status === 'stopped'

  return (
    <>
      {/* 뒤로가기 링크 */}
      <div className="mb-4">
        <Link to="/bots" className="text-text-muted text-[13px] no-underline hover:text-text hover:underline">
          &larr; 봇 관리
        </Link>
      </div>

      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[20px] font-bold flex items-center gap-2">
            {bot.name || bot.bot_id}
            {bot.name && <span className="text-[14px] font-normal text-text-muted font-mono">{bot.bot_id}</span>}
            {isStopped && (
              <StatusBadge variant="warning">중지</StatusBadge>
            )}
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
          {canEdit && (
            <button onClick={() => setShowEditModal(true)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">설정 수정</button>
          )}
          {canStart && (
            <button onClick={() => start.mutate(bot.bot_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">시작</button>
          )}
          {canStop && (
            <button onClick={() => stop.mutate(bot.bot_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">중지</button>
          )}
        </div>
      </div>

      {/* 3열 정보 그리드 */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {/* 운용 전략 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">운용 전략</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">전략명</span>
              <span>{bot.strategy?.name || bot.strategy_name || '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">버전</span>
              <span>{bot.strategy?.version ? `v${bot.strategy.version}` : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">작성자</span>
              <span>{bot.strategy?.author || '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">설명</span>
              <span className="text-right max-w-[60%]">{bot.strategy?.description || '-'}</span>
            </div>
          </div>
        </div>

        {/* 실행 설정 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">실행 설정</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">모드</span>
              <StatusBadge variant={bot.mode === 'live' ? 'warning' : 'info'}>
                {bot.mode === 'live' ? '실전' : '모의'}
              </StatusBadge>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">상태</span>
              <StatusBadge variant={STATUS_VARIANT[bot.status] as 'positive'}>
                {BOT_STATUS_LABELS[bot.status]}
              </StatusBadge>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">실행 간격</span>
              <span>{bot.interval_seconds}초</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">대상 종목</span>
              <span className="font-mono">{bot.symbols?.length ? bot.symbols.join(', ') : '-'}</span>
            </div>
          </div>
        </div>

        {/* 예산 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">예산</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">배정 금액</span>
              <span>{formatKRW(bot.allocated_budget)}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">매수 금액</span>
              <span>-</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">체결 대기</span>
              <span>-</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">잔여 예산</span>
              <span>-</span>
            </div>
          </div>
        </div>
      </div>

      {/* 보유 종목 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">보유 종목</h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">종목</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">수량</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">평균단가</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">현재가</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">매수금액</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">평가금액</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">미실현 손익</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">수익률</th>
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={8} className="px-3 py-6 text-center text-text-muted text-[13px]">보유 종목이 없습니다</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 실행 로그 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">실행 로그</h3>
          {(bot.logs ?? []).length > 0 && (
            <span className="text-[12px] text-primary cursor-pointer hover:underline">전체 보기</span>
          )}
        </div>
        {(bot.logs ?? []).length === 0 ? (
          <div className="py-4 text-text-muted text-[13px] text-center">로그가 없습니다</div>
        ) : (
          <div className="space-y-0">
            {bot.logs.slice(0, 10).map((log, i) => (
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

      {/* 설정 수정 모달 */}
      {showEditModal && <BotEditModal bot={bot} onClose={() => setShowEditModal(false)} />}
    </>
  )
}

function BotEditModal({ bot, onClose }: { bot: BotDetailType; onClose: () => void }) {
  const { data: strategies } = useStrategies()
  const { data: treasury } = useTreasurySummary()
  const [name, setName] = useState(bot.name || '')
  const [strategyName, setStrategyName] = useState(bot.strategy_name || '')
  const [mode, setMode] = useState<BotMode>(bot.mode)
  const [intervalSeconds, setIntervalSeconds] = useState(bot.interval_seconds)
  const [budget, setBudget] = useState(bot.allocated_budget)

  const currentBudget = bot.allocated_budget
  const maxPossible = treasury ? currentBudget + treasury.unallocated : currentBudget

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-[18px] font-bold mb-5">Bot 설정 수정</h2>
        <div className="space-y-4">
          {/* Bot ID (읽기 전용) */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Bot ID</label>
            <input
              type="text"
              value={bot.bot_id}
              disabled
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] opacity-50 cursor-not-allowed"
            />
          </div>

          {/* 이름 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
            />
          </div>

          {/* 전략 선택 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">전략 선택</label>
            <select
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
            >
              <option value="">전략을 선택하세요</option>
              {(strategies ?? []).map((s) => (
                <option key={s.id} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>

          {/* Bot 유형 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Bot 유형</label>
            <div className="inline-flex rounded-lg border border-border overflow-hidden">
              <button
                type="button"
                onClick={() => setMode('paper')}
                className={`px-4 py-2 text-[13px] font-medium border-none cursor-pointer ${
                  mode === 'paper'
                    ? 'bg-primary text-white'
                    : 'bg-transparent text-text-muted hover:bg-surface-hover'
                }`}
              >
                모의투자
              </button>
              <button
                type="button"
                onClick={() => setMode('live')}
                className={`px-4 py-2 text-[13px] font-medium border-none cursor-pointer ${
                  mode === 'live'
                    ? 'bg-primary text-white'
                    : 'bg-transparent text-text-muted hover:bg-surface-hover'
                }`}
              >
                실전투자
              </button>
            </div>
          </div>

          {/* 실행 간격 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">실행 간격 (초)</label>
            <input
              type="number"
              value={intervalSeconds}
              onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              min={10}
              max={3600}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
            />
            <div className="text-[11px] text-text-muted mt-1">최소 10초 ~ 최대 3,600초 (1시간)</div>
          </div>

          {/* 배정예산 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">배정예산 (원)</label>
            <input
              type="number"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
            />
            <div className="text-[11px] text-text-muted mt-1">
              현재 배정예산: {formatKRW(currentBudget)} · 최대 가능: {formatKRW(maxPossible)}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">저장</button>
        </div>
      </div>
    </div>
  )
}
