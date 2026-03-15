import { useState } from 'react'
import { useAllocateBudget, useDeallocateBudget } from '../../hooks/useTreasury'

export default function AllocationForm({ botIds }: { botIds: string[] }) {
  const [botId, setBotId] = useState(botIds[0] ?? '')
  const [amount, setAmount] = useState('')
  const allocate = useAllocateBudget()
  const deallocate = useDeallocateBudget()

  const handleAction = (action: 'allocate' | 'deallocate') => {
    const numAmount = Number(amount)
    if (!botId || !numAmount) return
    if (action === 'allocate') {
      allocate.mutate({ botId, amount: numAmount }, { onSuccess: () => setAmount('') })
    } else {
      deallocate.mutate({ botId, amount: numAmount }, { onSuccess: () => setAmount('') })
    }
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-4">할당 / 회수</h3>
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-[12px] font-semibold text-text-muted mb-1.5">봇</label>
          <select
            value={botId}
            onChange={(e) => setBotId(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px]"
          >
            {botIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-[12px] font-semibold text-text-muted mb-1.5">금액 (원)</label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
          />
        </div>
        <button
          onClick={() => handleAction('allocate')}
          disabled={!botId || !amount}
          className="px-4 py-2.5 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover disabled:opacity-50"
        >
          할당
        </button>
        <button
          onClick={() => handleAction('deallocate')}
          disabled={!botId || !amount}
          className="px-4 py-2.5 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text disabled:opacity-50"
        >
          회수
        </button>
      </div>
    </div>
  )
}
