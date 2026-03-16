import { useState } from 'react'
import { useAllocateBudget, useDeallocateBudget } from '../../hooks/useTreasury'
import { formatKRW } from '../../utils/formatters'
import type { BotBudget } from '../../types/treasury'

interface AllocationFormProps {
  budgets: BotBudget[]
}

export default function AllocationForm({ budgets }: AllocationFormProps) {
  const [botId, setBotId] = useState(budgets[0]?.bot_id ?? '')
  const [amount, setAmount] = useState('')
  const [confirmAction, setConfirmAction] = useState<{ action: 'allocate' | 'deallocate'; botId: string; amount: number } | null>(null)
  const allocate = useAllocateBudget()
  const deallocate = useDeallocateBudget()

  const selectedBudget = budgets.find((b) => b.bot_id === botId)
  const numAmount = Number(amount)

  const handleSubmit = () => {
    if (!confirmAction) return
    const { action, botId: bid, amount: amt } = confirmAction
    if (action === 'allocate') {
      allocate.mutate({ botId: bid, amount: amt }, { onSuccess: () => { setAmount(''); setConfirmAction(null) } })
    } else {
      deallocate.mutate({ botId: bid, amount: amt }, { onSuccess: () => { setAmount(''); setConfirmAction(null) } })
    }
  }

  return (
    <>
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-2">Bot 예산 관리</h3>
        <div className="text-[12px] text-text-muted mb-4">예산 변경은 Bot이 중지된 상태에서만 가능합니다.</div>

        <div className="space-y-4">
          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Bot 선택</label>
            <select
              value={botId}
              onChange={(e) => setBotId(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px]"
            >
              {budgets.map((b) => (
                <option key={b.bot_id} value={b.bot_id}>{b.bot_id}</option>
              ))}
            </select>
          </div>

          {selectedBudget && (
            <div>
              <label className="block text-[12px] font-semibold text-text-muted mb-1.5">현재 배정예산</label>
              <div className="text-[15px] font-semibold">{formatKRW(selectedBudget.allocated)}</div>
            </div>
          )}

          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">금액 (원)</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0"
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => numAmount > 0 && botId && setConfirmAction({ action: 'allocate', botId, amount: numAmount })}
              disabled={!botId || !numAmount}
              className="flex-1 px-4 py-2.5 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover disabled:opacity-50"
            >
              할당
            </button>
            <button
              onClick={() => numAmount > 0 && botId && setConfirmAction({ action: 'deallocate', botId, amount: numAmount })}
              disabled={!botId || !numAmount}
              className="flex-1 px-4 py-2.5 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text disabled:opacity-50"
            >
              회수
            </button>
          </div>
        </div>
      </div>

      {/* 확인 모달 */}
      {confirmAction && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[420px]">
            <h3 className="text-[16px] font-bold mb-3">
              예산 {confirmAction.action === 'allocate' ? '할당' : '회수'} 확인
            </h3>
            <div className="text-[13px] text-text-muted mb-4">아래 내용으로 예산을 변경합니다.</div>
            <div className="bg-bg border border-border rounded-lg p-4 mb-4 space-y-2">
              <div className="flex justify-between text-[13px]">
                <span className="text-text-muted">Bot</span>
                <span className="font-semibold font-mono">{confirmAction.botId}</span>
              </div>
              {selectedBudget && (
                <div className="flex justify-between text-[13px]">
                  <span className="text-text-muted">현재 예산</span>
                  <span>{formatKRW(selectedBudget.allocated)}</span>
                </div>
              )}
              <div className="flex justify-between text-[13px]">
                <span className="text-text-muted">{confirmAction.action === 'allocate' ? '할당' : '회수'} 금액</span>
                <span className={`font-semibold ${confirmAction.action === 'allocate' ? 'text-positive' : 'text-negative'}`}>
                  {confirmAction.action === 'allocate' ? '+' : '-'}{formatKRW(confirmAction.amount)}
                </span>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmAction(null)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
              <button onClick={handleSubmit} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">변경 확인</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
