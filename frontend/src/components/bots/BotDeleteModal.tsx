import { useState } from 'react'
import type { Bot } from '../../types/bot'

export type DeleteOption = 'force_liquidate' | 'keep'

interface BotDeleteModalProps {
  bot: Bot & {
    positions?: { symbol: string; quantity: number }[]
  }
  onConfirm: (option?: DeleteOption) => void
  onClose: () => void
  isPending?: boolean
}

export default function BotDeleteModal({ bot, onConfirm, onClose, isPending }: BotDeleteModalProps) {
  const positions = bot.positions?.filter((p) => p.quantity > 0) ?? []
  const hasPositions = positions.length > 0
  const [deleteOption, setDeleteOption] = useState<DeleteOption>('keep')

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-[18px] font-bold mb-4 text-negative">Bot 삭제</h2>

        <div className="text-[13px] text-text-muted mb-4">
          {hasPositions
            ? '보유 종목이 있습니다. 삭제 전 포지션 처리 방법을 선택해주세요.'
            : 'Bot을 삭제하면 더 이상 실행할 수 없습니다.'
          }
        </div>

        {/* 거래 이력 보존 안내 */}
        <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg bg-info-bg border border-info/25 text-info text-[13px] mb-4">
          <span className="text-[15px]">&#9432;</span>
          <span>거래 이력과 성과 기록은 보존됩니다.</span>
        </div>

        {/* Bot 정보 */}
        <div className="bg-bg border border-border rounded-lg p-3.5 mb-4">
          <div className="flex justify-between mb-2 text-[13px]">
            <span className="text-text-muted">Bot</span>
            <span>
              <span className="font-semibold">{bot.name || bot.bot_id}</span>
              {bot.name && <span className="font-normal text-text-muted ml-1">{bot.bot_id}</span>}
            </span>
          </div>
          <div className="flex justify-between text-[13px]">
            <span className="text-text-muted">보유 종목</span>
            <span>{hasPositions ? `${positions.length}종목` : '없음'}</span>
          </div>
        </div>

        {/* 포지션 처리 옵션 (보유종목 있을 때만) */}
        {hasPositions && (
          <div className="flex flex-col gap-2 mb-4">
            <label className="flex items-start gap-2.5 p-3 border border-border rounded-lg cursor-pointer hover:bg-surface-hover">
              <input
                type="radio"
                name="deleteOption"
                checked={deleteOption === 'force_liquidate'}
                onChange={() => setDeleteOption('force_liquidate')}
                className="mt-0.5"
              />
              <div>
                <div className="text-[13px] font-medium">강제 청산 후 삭제</div>
                <div className="text-[12px] text-text-muted">보유 종목을 전량 시장가 매도한 후 Bot을 삭제합니다</div>
              </div>
            </label>
            <label className="flex items-start gap-2.5 p-3 border border-border rounded-lg cursor-pointer hover:bg-surface-hover">
              <input
                type="radio"
                name="deleteOption"
                checked={deleteOption === 'keep'}
                onChange={() => setDeleteOption('keep')}
                className="mt-0.5"
              />
              <div>
                <div className="text-[13px] font-medium">포지션 유지 후 삭제</div>
                <div className="text-[12px] text-text-muted">보유 종목을 유지한 채 Bot만 삭제합니다. 포지션은 운영자가 직접 관리해야 합니다.</div>
              </div>
            </label>
          </div>
        )}

        {/* 버튼 */}
        <div className="flex justify-end gap-2 pt-4 border-t border-border">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">
            취소
          </button>
          <button
            type="button"
            onClick={() => onConfirm(hasPositions ? deleteOption : undefined)}
            disabled={isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative/80 disabled:opacity-50"
          >
            {isPending ? '삭제 중...' : '삭제'}
          </button>
        </div>
      </div>
    </div>
  )
}
