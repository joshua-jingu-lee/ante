import type { Bot } from '../../types/bot'
import { formatKRW } from '../../utils/formatters'

interface BotStopModalProps {
  bot: Bot & {
    positions?: { symbol: string; quantity: number }[]
    budget?: { reserved: number }
  }
  onConfirm: () => void
  onClose: () => void
  isPending?: boolean
}

export default function BotStopModal({ bot, onConfirm, onClose, isPending }: BotStopModalProps) {
  const positions = bot.positions?.filter((p) => p.quantity > 0) ?? []
  const hasPositions = positions.length > 0
  const positionNames = positions.map((p) => p.symbol).join(', ')
  const reserved = bot.budget?.reserved ?? 0

  return (
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-[18px] font-bold mb-4 text-negative">Bot 중지</h2>

        <div className="text-[13px] text-text-muted mb-4">
          Bot을 중지하면 현재 실행 중인 전략 사이클이 완료된 후 중지됩니다.<br />
          미체결 주문은 취소되지 않습니다.
        </div>

        {/* 보유종목 있음 경고 배너 */}
        {hasPositions && (
          <div className="bg-warning-bg text-warning px-3.5 py-2.5 rounded text-[12px] mb-4">
            &#9888; 보유 종목 {positions.length}개가 유지됩니다. 중지 후 포지션을 직접 관리해야 합니다.
          </div>
        )}

        {/* Bot 정보 */}
        <div className="bg-bg border border-border rounded-lg p-3.5 mb-4">
          <div className="flex justify-between mb-2 text-[13px]">
            <span className="text-text-muted">Bot</span>
            <span>
              <span className="font-semibold">{bot.name || bot.bot_id}</span>
              {bot.name && <span className="font-normal text-text-muted ml-1">{bot.bot_id}</span>}
            </span>
          </div>
          <div className="flex justify-between mb-2 text-[13px]">
            <span className="text-text-muted">보유 종목</span>
            <span>{hasPositions ? `${positions.length}종목 (${positionNames})` : '없음'}</span>
          </div>
          {(hasPositions || reserved > 0) && (
            <div className="flex justify-between text-[13px]">
              <span className="text-text-muted">체결대기</span>
              <span>{formatKRW(reserved)}</span>
            </div>
          )}
        </div>

        {/* 버튼 */}
        <div className="flex justify-end gap-2 pt-4 border-t border-border">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-on-primary border-none cursor-pointer hover:bg-negative/80 disabled:opacity-50"
          >
            {isPending ? '중지 중...' : '중지 확인'}
          </button>
        </div>
      </div>
    </div>
  )
}
