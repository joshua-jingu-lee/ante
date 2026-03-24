import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useBotDetail, useBotControl, useBotUpdate } from '../hooks/useBots'
import { useStrategies } from '../hooks/useStrategies'
import { useTreasurySummary } from '../hooks/useTreasury'
import StatusBadge from '../components/common/StatusBadge'
import HintTooltip from '../components/common/HintTooltip'
import { PageSkeleton } from '../components/common/Skeleton'
import BotStopModal from '../components/bots/BotStopModal'
import BotDeleteModal from '../components/bots/BotDeleteModal'
import { formatKRW, formatDateTime, formatPercent } from '../utils/formatters'
import { BOT_STATUS_LABELS } from '../utils/constants'
import type { BotStatus, BotDetail as BotDetailType, BotLogResult, HandlePositions } from '../types/bot'

const STATUS_VARIANT: Record<BotStatus, string> = {
  created: 'muted', running: 'positive', stopping: 'warning', stopped: 'warning', error: 'negative', deleted: 'muted',
}

export default function BotDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: bot, isLoading } = useBotDetail(id!)
  const { start, stop, remove } = useBotControl()
  const [showEditModal, setShowEditModal] = useState(false)
  const [showStopModal, setShowStopModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  if (isLoading) return <PageSkeleton />
  if (!bot) return <div className="text-text-muted text-center py-12">봇을 찾을 수 없습니다</div>

  const canStart = bot.status === 'stopped' || bot.status === 'created'
  const canStop = bot.status === 'running'
  const canEdit = bot.status === 'stopped' || bot.status === 'created'
  return (
    <>
      {/* 뒤로가기 링크 */}
      <div className="mb-4">
        <Link to="/bots" className="inline-flex items-center text-text-muted text-[13px] no-underline px-2 py-1 rounded hover:bg-surface-hover hover:text-text">
          &larr; 봇 관리
        </Link>
      </div>

      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-[18px] font-bold flex items-center gap-2">
            {bot.name || bot.bot_id}
            {bot.name && <span className="text-[15px] font-normal text-text-muted">{bot.bot_id}</span>}
          </h2>
        </div>
        <div className="flex gap-2">
          {canEdit && (
            <button onClick={() => setShowDeleteModal(true)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-negative border border-negative cursor-pointer hover:bg-negative-bg">삭제</button>
          )}
          {canEdit && (
            <button onClick={() => setShowEditModal(true)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">설정 수정</button>
          )}
          {canStart && (
            <button onClick={() => start.mutate(bot.bot_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover">시작</button>
          )}
          {canStop && (
            <button onClick={() => setShowStopModal(true)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-negative border border-negative cursor-pointer hover:bg-negative-bg">중지</button>
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
              <span>{bot.strategy?.name || bot.strategy_name ? <Link to="/strategies" className="text-primary no-underline hover:underline">{bot.strategy?.name || bot.strategy_name}</Link> : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">버전</span>
              <span>{bot.strategy?.version ? `v${bot.strategy.version}` : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">작성자</span>
              <span>
                {bot.strategy_author_name || bot.strategy?.author || '-'}
                {bot.strategy_author_id && (
                  <span className="text-text-muted text-[12px] ml-1">({bot.strategy_author_id})</span>
                )}
              </span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">설명</span>
              <span className="text-right max-w-[60%] text-[12px] text-text-muted">{bot.strategy?.description || '-'}</span>
            </div>
          </div>
        </div>

        {/* 실행 설정 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">실행 설정</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">상태</span>
              <StatusBadge variant={STATUS_VARIANT[bot.status] as 'positive'}>
                {BOT_STATUS_LABELS[bot.status]}
              </StatusBadge>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">실행 간격</span>
              <span>{bot.config?.interval_seconds ?? bot.interval_seconds}초</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">자동 재시작</span>
              {bot.config ? (
                <StatusBadge variant={bot.config.auto_restart ? 'positive' : 'muted'}>
                  {bot.config.auto_restart ? 'ON' : 'OFF'}
                </StatusBadge>
              ) : <span>-</span>}
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">최대 재시작</span>
              <span>{bot.config ? `${bot.config.max_restart_attempts}회` : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted flex items-center">재시작 쿨다운<HintTooltip text="재시작 시도 사이의 대기 시간" /></span>
              <span>{bot.config ? `${bot.config.restart_cooldown_seconds}초` : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted flex items-center">스텝 타임아웃<HintTooltip text="전략의 1회 실행(on_step)이 이 시간을 초과하면 경고" /></span>
              <span>{bot.config ? `${bot.config.step_timeout_seconds}초` : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted flex items-center">스텝당 최대 시그널<HintTooltip text="전략의 1회 실행에서 발생할 수 있는 매매 신호 수 상한" /></span>
              <span>{bot.config?.max_signals_per_step ?? '-'}</span>
            </div>
          </div>
        </div>

        {/* 예산 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-3">예산</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">배정금액</span>
              <span>{formatKRW(bot.budget?.allocated ?? bot.allocated_budget)}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">매수금액</span>
              <span>{bot.budget ? formatKRW(bot.budget.spent) : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">체결대기</span>
              <span>{bot.budget ? formatKRW(bot.budget.reserved) : '-'}</span>
            </div>
            <div className="flex justify-between py-1.5 text-[13px]">
              <span className="text-text-muted">잔여예산</span>
              <span>{bot.budget ? formatKRW(bot.budget.available) : '-'}</span>
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
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">실현 손익</th>
              </tr>
            </thead>
            <tbody>
              {(!bot.positions || bot.positions.length === 0) ? (
                <tr><td colSpan={9} className="px-3 py-6 text-center text-text-muted text-[13px]">보유 종목이 없습니다</td></tr>
              ) : (
                bot.positions.map((pos) => {
                  const isClosed = pos.quantity === 0
                  const cost = isClosed ? 0 : pos.quantity * pos.avg_entry_price
                  const evalAmount = isClosed ? 0 : pos.quantity * (pos.current_price ?? pos.avg_entry_price)
                  const unrealizedPnl = isClosed ? 0 : evalAmount - cost
                  const returnRate = isClosed ? 0 : cost > 0 ? unrealizedPnl / cost : 0
                  const pnlColor = (v: number) => v > 0 ? 'text-positive' : v < 0 ? 'text-negative' : 'text-text-muted'

                  return (
                    <tr key={pos.symbol} className="border-b border-border">
                      <td className="px-3 py-2 text-[13px]">{pos.symbol}</td>
                      <td className="text-right px-3 py-2 text-[13px]">{pos.quantity}</td>
                      <td className="text-right px-3 py-2 text-[13px]">{isClosed ? '—' : formatKRW(pos.avg_entry_price)}</td>
                      <td className="text-right px-3 py-2 text-[13px]">{isClosed ? '—' : formatKRW(pos.current_price ?? pos.avg_entry_price)}</td>
                      <td className="text-right px-3 py-2 text-[13px]">{isClosed ? '—' : formatKRW(cost)}</td>
                      <td className="text-right px-3 py-2 text-[13px]">{isClosed ? '—' : formatKRW(evalAmount)}</td>
                      <td className={`text-right px-3 py-2 text-[13px] ${isClosed ? 'text-text-muted' : pnlColor(unrealizedPnl)}`}>
                        {isClosed ? '—' : formatKRW(unrealizedPnl)}
                      </td>
                      <td className={`text-right px-3 py-2 text-[13px] ${isClosed ? 'text-text-muted' : pnlColor(returnRate)}`}>
                        {isClosed ? '—' : formatPercent(returnRate)}
                      </td>
                      <td className={`text-right px-3 py-2 text-[13px] ${pnlColor(pos.realized_pnl)}`}>
                        {formatKRW(pos.realized_pnl)}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 실행 로그 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">실행 로그</h3>
          {(bot.logs ?? []).length > 0 && (
            <span className="text-[13px] text-primary cursor-pointer hover:underline">전체 보기 &rarr;</span>
          )}
        </div>
        {(bot.logs ?? []).length === 0 ? (
          <div className="py-4 text-text-muted text-[13px] text-center">로그가 없습니다</div>
        ) : (
          <div className="space-y-0">
            {bot.logs.slice(0, 10).map((log, i) => {
              const result: BotLogResult = log.result ?? (log.success ? 'success' : 'failure')
              const variant = result === 'success' ? 'positive' : result === 'stopped' ? 'warning' : 'negative'
              const label = result === 'success' ? '성공' : result === 'stopped' ? '중지' : '실패'
              return (
                <div key={i} className="flex gap-3 py-2 border-b border-border text-[13px]">
                  <span className="text-text-muted font-mono text-[12px] whitespace-nowrap">{formatDateTime(log.timestamp)}</span>
                  <StatusBadge variant={variant}>{label}</StatusBadge>
                  {log.message && <span className={result === 'failure' ? 'text-negative' : ''}>{log.message}</span>}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 중지 확인 모달 */}
      {showStopModal && (
        <BotStopModal
          bot={bot}
          onConfirm={() => {
            stop.mutate(bot.bot_id, { onSuccess: () => setShowStopModal(false) })
          }}
          onClose={() => setShowStopModal(false)}
          isPending={stop.isPending}
        />
      )}

      {/* 삭제 확인 모달 */}
      {showDeleteModal && (
        <BotDeleteModal
          bot={bot}
          onConfirm={(option) => {
            const handlePositions: HandlePositions | undefined = option === 'force_liquidate' ? 'liquidate' : option === 'keep' ? 'keep' : undefined
            remove.mutate(
              { botId: bot.bot_id, handlePositions },
              { onSuccess: () => navigate('/bots') },
            )
          }}
          onClose={() => setShowDeleteModal(false)}
          isPending={remove.isPending}
        />
      )}

      {/* 설정 수정 모달 */}
      {showEditModal && <BotEditModal bot={bot} onClose={() => setShowEditModal(false)} />}
    </>
  )
}

function BotEditModal({ bot, onClose }: { bot: BotDetailType; onClose: () => void }) {
  const { data: strategies } = useStrategies()
  const { data: treasury } = useTreasurySummary()
  const updateMutation = useBotUpdate()
  const [name, setName] = useState(bot.name || '')
  const [strategyName, setStrategyName] = useState(bot.strategy_name || '')
  const [intervalSeconds, setIntervalSeconds] = useState(bot.config?.interval_seconds ?? bot.interval_seconds)
  const [budget, setBudget] = useState(bot.allocated_budget)
  const [autoRestart, setAutoRestart] = useState(bot.config?.auto_restart ?? true)
  const [maxRestartAttempts, setMaxRestartAttempts] = useState(bot.config?.max_restart_attempts ?? 3)
  const [restartCooldownSeconds, setRestartCooldownSeconds] = useState(bot.config?.restart_cooldown_seconds ?? 60)
  const [stepTimeoutSeconds, setStepTimeoutSeconds] = useState(bot.config?.step_timeout_seconds ?? 30)
  const [maxSignalsPerStep, setMaxSignalsPerStep] = useState(bot.config?.max_signals_per_step ?? 50)

  const currentBudget = bot.allocated_budget
  const maxPossible = treasury ? currentBudget + treasury.unallocated : currentBudget

  const handleSave = () => {
    updateMutation.mutate(
      {
        botId: bot.bot_id,
        data: {
          name,
          interval_seconds: intervalSeconds,
          budget,
          auto_restart: autoRestart,
          max_restart_attempts: maxRestartAttempts,
          restart_cooldown_seconds: restartCooldownSeconds,
          step_timeout_seconds: stepTimeoutSeconds,
          max_signals_per_step: maxSignalsPerStep,
        },
      },
      { onSuccess: () => onClose() },
    )
  }

  const inputClass = 'w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary'

  return (
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
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
              className={inputClass}
            />
          </div>

          {/* 전략 선택 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">전략 선택</label>
            <select
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              className={inputClass}
            >
              <option value="">전략을 선택하세요</option>
              {(strategies ?? []).map((s) => (
                <option key={s.id} value={s.name}>{s.name}</option>
              ))}
            </select>
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
              className={inputClass}
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
              className={inputClass}
            />
            <div className="text-[11px] text-text-muted mt-1">
              현재 배정예산: {formatKRW(currentBudget)} · 최대 가능: {formatKRW(maxPossible)}
            </div>
          </div>

          {/* 자동 재시작 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">자동 재시작</label>
            <button
              type="button"
              onClick={() => setAutoRestart(!autoRestart)}
              className={`px-4 py-2.5 rounded-lg text-[14px] font-medium border cursor-pointer w-full text-left ${
                autoRestart
                  ? 'bg-positive-bg text-positive border-positive/25'
                  : 'bg-bg text-text-muted border-border'
              }`}
            >
              {autoRestart ? 'ON' : 'OFF'}
            </button>
          </div>

          {/* 최대 재시작 횟수 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">최대 재시작 횟수</label>
            <input
              type="number"
              value={maxRestartAttempts}
              onChange={(e) => setMaxRestartAttempts(Number(e.target.value))}
              min={1}
              max={10}
              className={inputClass}
            />
            <div className="text-[11px] text-text-muted mt-1">1~10회</div>
          </div>

          {/* 재시작 쿨다운 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5 flex items-center">
              재시작 쿨다운 (초)<HintTooltip text="재시작 시도 사이의 대기 시간" />
            </label>
            <input
              type="number"
              value={restartCooldownSeconds}
              onChange={(e) => setRestartCooldownSeconds(Number(e.target.value))}
              min={10}
              max={600}
              className={inputClass}
            />
            <div className="text-[11px] text-text-muted mt-1">10~600초</div>
          </div>

          {/* 스텝 타임아웃 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5 flex items-center">
              스텝 타임아웃 (초)<HintTooltip text="전략의 1회 실행(on_step)이 이 시간을 초과하면 경고" />
            </label>
            <input
              type="number"
              value={stepTimeoutSeconds}
              onChange={(e) => setStepTimeoutSeconds(Number(e.target.value))}
              min={5}
              max={120}
              className={inputClass}
            />
            <div className="text-[11px] text-text-muted mt-1">5~120초</div>
          </div>

          {/* 스텝당 최대 시그널 */}
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5 flex items-center">
              스텝당 최대 시그널<HintTooltip text="전략의 1회 실행에서 발생할 수 있는 매매 신호 수 상한" />
            </label>
            <input
              type="number"
              value={maxSignalsPerStep}
              onChange={(e) => setMaxSignalsPerStep(Number(e.target.value))}
              min={1}
              max={200}
              className={inputClass}
            />
            <div className="text-[11px] text-text-muted mt-1">1~200</div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
          <button
            type="button"
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50"
          >
            {updateMutation.isPending ? '저장 중...' : '저장'}
          </button>
        </div>
      </div>
    </div>
  )
}
