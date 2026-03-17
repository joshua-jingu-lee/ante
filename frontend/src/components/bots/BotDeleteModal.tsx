import { useState } from 'react'
import type { Bot } from '../../types/bot'

interface Position {
  symbol: string
  quantity: number
  avg_price: number
  current_price: number
}

export type DeleteOption = 'force_liquidate' | 'manual_liquidate'

interface BotDeleteModalProps {
  bot: Bot
  positions?: Position[]
  onConfirm: (option?: DeleteOption) => void
  onClose: () => void
  isPending?: boolean
}

export default function BotDeleteModal({ bot, positions = [], onConfirm, onClose, isPending }: BotDeleteModalProps) {
  const hasPositions = positions.length > 0
  const [deleteOption, setDeleteOption] = useState<DeleteOption>('force_liquidate')

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-[18px] font-bold mb-5">봇 삭제</h2>

        {/* 보유종목 있음 경고 배너 */}
        {hasPositions && (
          <div className="flex items-start gap-2 bg-negative/10 border border-negative/30 rounded-lg px-4 py-3 mb-4">
            <span className="text-negative text-[16px] mt-0.5">&#9888;</span>
            <div className="text-[13px] text-negative">
              <span className="font-semibold">보유 종목 {positions.length}개가 있습니다</span>
              <p className="mt-1 text-negative/80">삭제 전 포지션 처리 방법을 선택하세요.</p>
            </div>
          </div>
        )}

        {/* 보유종목 없음 안내 */}
        {!hasPositions && (
          <div className="flex items-start gap-2 bg-primary/10 border border-primary/30 rounded-lg px-4 py-3 mb-4">
            <span className="text-primary text-[16px] mt-0.5">&#8505;</span>
            <div className="text-[13px] text-text-muted">
              거래 이력과 성과 기록은 보존됩니다.
            </div>
          </div>
        )}

        {/* Bot 정보 */}
        <div className="bg-bg rounded-lg p-4 mb-4">
          <div className="space-y-2 text-[13px]">
            <div className="flex justify-between">
              <span className="text-text-muted">봇 이름</span>
              <span className="font-medium">{bot.name || bot.bot_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">봇 ID</span>
              <span className="font-mono text-[12px]">{bot.bot_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">보유 종목</span>
              <span>{hasPositions ? `${positions.length}개` : '없음'}</span>
            </div>
          </div>
        </div>

        {/* 포지션 처리 옵션 (보유종목 있을 때만) */}
        {hasPositions && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold text-text-muted mb-3">포지션 처리 방법</h3>
            <div className="space-y-2">
              <label
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  deleteOption === 'force_liquidate'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-surface-hover'
                }`}
              >
                <input
                  type="radio"
                  name="deleteOption"
                  checked={deleteOption === 'force_liquidate'}
                  onChange={() => setDeleteOption('force_liquidate')}
                  className="mt-0.5 accent-primary"
                />
                <div>
                  <div className="text-[13px] font-medium">강제 청산 후 삭제</div>
                  <div className="text-[12px] text-text-muted mt-0.5">
                    모든 보유 종목을 시장가로 즉시 매도한 뒤 봇을 삭제합니다.
                  </div>
                </div>
              </label>
              <label
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  deleteOption === 'manual_liquidate'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-surface-hover'
                }`}
              >
                <input
                  type="radio"
                  name="deleteOption"
                  checked={deleteOption === 'manual_liquidate'}
                  onChange={() => setDeleteOption('manual_liquidate')}
                  className="mt-0.5 accent-primary"
                />
                <div>
                  <div className="text-[13px] font-medium">직접 청산</div>
                  <div className="text-[12px] text-text-muted mt-0.5">
                    봇을 중지 상태로 전환합니다. 보유 종목을 직접 청산한 뒤 다시 삭제하세요.
                  </div>
                </div>
              </label>
            </div>

            {/* 보유종목 테이블 */}
            <div className="mt-4">
              <h3 className="text-[13px] font-semibold text-text-muted mb-2">보유 종목</h3>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[12px]">
                  <thead>
                    <tr>
                      <th className="text-left px-2 py-1.5 font-semibold text-text-muted border-b border-border">종목</th>
                      <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-b border-border">수량</th>
                      <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-b border-border">평균단가</th>
                      <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-b border-border">현재가</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos) => (
                      <tr key={pos.symbol}>
                        <td className="px-2 py-1.5 font-mono border-b border-border/50">{pos.symbol}</td>
                        <td className="text-right px-2 py-1.5 border-b border-border/50">{pos.quantity.toLocaleString()}</td>
                        <td className="text-right px-2 py-1.5 border-b border-border/50">{pos.avg_price.toLocaleString()}원</td>
                        <td className="text-right px-2 py-1.5 border-b border-border/50">{pos.current_price.toLocaleString()}원</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* 버튼 */}
        <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">
            취소
          </button>
          <button
            type="button"
            onClick={() => onConfirm(hasPositions ? deleteOption : undefined)}
            disabled={isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative/80 disabled:opacity-50"
          >
            {isPending ? '삭제 중...' : hasPositions && deleteOption === 'manual_liquidate' ? '중지로 전환' : '삭제'}
          </button>
        </div>
      </div>
    </div>
  )
}
