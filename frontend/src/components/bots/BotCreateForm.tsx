import { useState } from 'react'
import { useCreateBot } from '../../hooks/useBots'
import type { BotMode } from '../../types/bot'

interface BotCreateFormProps {
  onClose: () => void
}

export default function BotCreateForm({ onClose }: BotCreateFormProps) {
  const [botId, setBotId] = useState('')
  const [name, setName] = useState('')
  const [strategyName, setStrategyName] = useState('')
  const [mode, setMode] = useState<BotMode>('paper')
  const [interval, setInterval] = useState('60')
  const [budget, setBudget] = useState('')
  const [symbols, setSymbols] = useState('')
  const createBot = useCreateBot()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createBot.mutate(
      {
        bot_id: botId,
        name,
        strategy_name: strategyName,
        mode,
        interval_seconds: Number(interval),
        budget: Number(budget),
        symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-[18px] font-bold mb-5">봇 생성</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="모멘텀 돌파 봇" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" />
            <div className="text-[11px] text-text-muted mt-1">대시보드에 표시되는 이름</div>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">봇 ID</label>
            <input value={botId} onChange={(e) => setBotId(e.target.value)} placeholder="bot-momentum-01" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">전략</label>
            <input value={strategyName} onChange={(e) => setStrategyName(e.target.value)} placeholder="전략명" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">봇 유형</label>
            <div className="flex gap-2">
              <button type="button" onClick={() => setMode('paper')} className={`flex-1 py-2 rounded-lg text-[13px] font-medium border cursor-pointer ${mode === 'paper' ? 'bg-primary text-white border-primary' : 'bg-transparent text-text-muted border-border hover:bg-surface-hover'}`}>모의투자</button>
              <button type="button" onClick={() => setMode('live')} className={`flex-1 py-2 rounded-lg text-[13px] font-medium border cursor-pointer ${mode === 'live' ? 'bg-warning text-black border-warning' : 'bg-transparent text-text-muted border-border hover:bg-surface-hover'}`}>실전투자</button>
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">실행 간격 (초)</label>
            <input type="number" value={interval} onChange={(e) => setInterval(e.target.value)} className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">예산 (원)</label>
            <input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="5000000" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">대상 종목 (콤마 구분)</label>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="005930, 035420" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" />
            <div className="text-[11px] text-text-muted mt-1">선택사항</div>
          </div>
          <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
            <button type="submit" disabled={createBot.isPending} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50">생성</button>
          </div>
        </form>
      </div>
    </div>
  )
}
