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
  const [showConfirm, setShowConfirm] = useState(false)
  const allocate = useAllocateBudget()
  const deallocate = useDeallocateBudget()

  const selectedBudget = budgets.find((b) => b.bot_id === botId)
  const numAmount = Number(amount.replace(/,/g, ''))

  const handleSubmit = () => {
    if (!selectedBudget || !numAmount) return
    const diff = numAmount - selectedBudget.allocated
    if (diff > 0) {
      allocate.mutate({ botId, amount: diff }, { onSuccess: () => { setAmount(''); setShowConfirm(false) } })
    } else if (diff < 0) {
      deallocate.mutate({ botId, amount: Math.abs(diff) }, { onSuccess: () => { setAmount(''); setShowConfirm(false) } })
    } else {
      setShowConfirm(false)
    }
  }

  const diff = selectedBudget ? numAmount - selectedBudget.allocated : 0

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
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-text text-[14px] h-[38px]"
            >
              {budgets.map((b) => (
                <option key={b.bot_id} value={b.bot_id}>{b.bot_id}</option>
              ))}
            </select>
          </div>

          {selectedBudget && (
            <div>
              <label className="block text-[12px] font-semibold text-text-muted mb-1.5">현재 배정예산</label>
              <div className="text-[15px] font-semibold mb-2">{formatKRW(selectedBudget.allocated)}</div>
            </div>
          )}

          <div>
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">변경할 예산 (원)</label>
            <input
              type="text"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={selectedBudget ? new Intl.NumberFormat('ko-KR').format(selectedBudget.allocated) : '0'}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
            />
          </div>

          <button
            onClick={() => numAmount > 0 && botId && setShowConfirm(true)}
            disabled={!botId || !numAmount}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50"
          >
            예산 변경
          </button>
        </div>
      </div>

      {/* 예산 변경 확인 모달 */}
      {showConfirm && selectedBudget && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold mb-5">예산 변경 확인</h3>
            <div className="text-[13px] text-text-muted mb-4">아래 내용으로 예산을 변경합니다.</div>
            <div className="bg-bg border border-border rounded-lg p-4 mb-4 space-y-2">
              <div className="flex justify-between text-[13px]">
                <span className="text-text-muted">Bot</span>
                <span className="font-semibold">{botId}</span>
              </div>
              <div className="flex justify-between text-[13px]">
                <span className="text-text-muted">현재 예산</span>
                <span>{formatKRW(selectedBudget.allocated)}</span>
              </div>
              <div className="flex justify-between text-[13px]">
                <span className="text-text-muted">변경 예산</span>
                <span className="font-semibold">{formatKRW(numAmount)}</span>
              </div>
              <div className="flex justify-between text-[13px] border-t border-border pt-2">
                <span className="text-text-muted">차액</span>
                <span className={`font-semibold ${diff >= 0 ? 'text-positive' : 'text-negative'}`}>
                  {diff >= 0 ? '+' : ''}{formatKRW(diff)}
                </span>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
              <button onClick={() => setShowConfirm(false)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
              <button onClick={handleSubmit} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">변경 확인</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
