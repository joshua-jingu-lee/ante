import { useState, useEffect } from 'react'
import { useCreateBot } from '../../hooks/useBots'
import { useStrategies } from '../../hooks/useStrategies'
import { useActiveAccounts } from '../../hooks/useAccounts'
import { useTreasurySummary } from '../../hooks/useTreasury'
import { formatNumber } from '../../utils/formatters'

interface BotCreateFormProps {
  onClose: () => void
}

const BOT_ID_PATTERN = /^[a-zA-Z0-9-]+$/

export default function BotCreateForm({ onClose }: BotCreateFormProps) {
  const [botId, setBotId] = useState('')
  const [name, setName] = useState('')
  const [strategyId, setStrategyId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [interval, setInterval] = useState('60')
  const [budget, setBudget] = useState('')
  const [botIdError, setBotIdError] = useState('')
  const createBot = useCreateBot()
  const { data: strategies } = useStrategies()
  const { data: accounts, isLoading: accountsLoading } = useActiveAccounts()
  const { data: treasury } = useTreasurySummary()

  const adoptedStrategies = strategies?.filter((s) => s.status === 'adopted') ?? []
  const remainingBudget = treasury?.unallocated ?? 0

  const activeAccounts = accounts ?? []

  // 활성 계좌가 1개면 자동 선택
  useEffect(() => {
    if (activeAccounts.length === 1 && !accountId) {
      setAccountId(activeAccounts[0].account_id)
    }
  }, [activeAccounts, accountId])

  const validateBotId = (value: string) => {
    if (value && !BOT_ID_PATTERN.test(value)) {
      setBotIdError('영문, 숫자, 하이픈만 사용 가능합니다')
    } else {
      setBotIdError('')
    }
  }

  const handleBotIdChange = (value: string) => {
    setBotId(value)
    validateBotId(value)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (botId && !BOT_ID_PATTERN.test(botId)) return
    createBot.mutate(
      {
        bot_id: botId,
        name,
        strategy_id: strategyId,
        account_id: accountId || undefined,
        interval_seconds: Number(interval),
        budget: Number(budget.replace(/,/g, '')),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-[18px] font-bold mb-5">봇 생성</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Bot ID</label>
            <input value={botId} onChange={(e) => handleBotIdChange(e.target.value)} placeholder="my-bot-01" className={`w-full bg-bg border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary ${botIdError ? 'border-negative' : 'border-border'}`} required />
            {botIdError ? (
              <div className="text-[11px] text-negative mt-1">{botIdError}</div>
            ) : (
              <div className="text-[11px] text-text-muted mt-1">영문, 숫자, 하이픈만 사용 가능 (고유값)</div>
            )}
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="모멘텀 돌파 봇" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" />
            <div className="text-[11px] text-text-muted mt-1">대시보드에 표시되는 이름</div>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">전략 선택</label>
            <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)} className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" required disabled={adoptedStrategies.length === 0}>
              <option value="">{adoptedStrategies.length === 0 ? '채택된 전략이 없습니다' : '전략을 선택하세요'}</option>
              {adoptedStrategies.map((s) => (
                <option key={s.id} value={String(s.id)}>{s.name} {s.version} ({s.id})</option>
              ))}
            </select>
            {adoptedStrategies.length === 0 && (
              <div className="text-[11px] text-warning mt-1">봇을 생성하려면 먼저 전략을 채택해 주세요</div>
            )}
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">계좌 선택</label>
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              required
              disabled={accountsLoading || activeAccounts.length === 0}
            >
              {accountsLoading ? (
                <option value="">계좌 목록 로딩 중...</option>
              ) : activeAccounts.length === 0 ? (
                <option value="">활성 계좌가 없습니다</option>
              ) : activeAccounts.length === 1 ? (
                <option value={activeAccounts[0].account_id}>
                  {activeAccounts[0].name} ({activeAccounts[0].exchange} / {activeAccounts[0].trading_mode})
                </option>
              ) : (
                <>
                  <option value="">계좌를 선택하세요</option>
                  {activeAccounts.map((acc) => (
                    <option key={acc.account_id} value={acc.account_id}>
                      {acc.name} ({acc.exchange} / {acc.trading_mode})
                    </option>
                  ))}
                </>
              )}
            </select>
            {!accountsLoading && activeAccounts.length === 0 && (
              <div className="text-[11px] text-warning mt-1">봇을 생성하려면 먼저 계좌를 등록해 주세요</div>
            )}
            {!accountsLoading && activeAccounts.length === 1 && (
              <div className="text-[11px] text-text-muted mt-1">활성 계좌가 1개뿐이므로 자동 선택되었습니다</div>
            )}
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">실행 간격 (초)</label>
            <input type="number" value={interval} onChange={(e) => setInterval(e.target.value)} min={10} max={3600} className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" />
            <div className="text-[11px] text-text-muted mt-1">최소 10초 ~ 최대 3,600초 (1시간)</div>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">배정예산 (원)</label>
            <input type="text" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="5,000,000" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
            <div className="text-[11px] text-text-muted mt-1">잔여예산: {formatNumber(remainingBudget)} 원</div>
          </div>
          <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
            <button type="submit" disabled={createBot.isPending || !!botIdError} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50">생성</button>
          </div>
        </form>
      </div>
    </div>
  )
}
