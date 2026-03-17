import type { Bot } from '../../types/bot'

interface Position {
  symbol: string
  quantity: number
  avg_price: number
  current_price: number
}

interface PendingOrder {
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
}

interface BotStopModalProps {
  bot: Bot
  positions?: Position[]
  pendingOrders?: PendingOrder[]
  onConfirm: () => void
  onClose: () => void
  isPending?: boolean
}

export default function BotStopModal({ bot, positions = [], pendingOrders = [], onConfirm, onClose, isPending }: BotStopModalProps) {
  const hasPositions = positions.length > 0
  const hasPendingOrders = pendingOrders.length > 0

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]" onClick={onClose}>
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-[18px] font-bold mb-5">봇 중지</h2>

        {/* 보유종목 있음 경고 배너 */}
        {hasPositions && (
          <div className="flex items-start gap-2 bg-warning/10 border border-warning/30 rounded-lg px-4 py-3 mb-4">
            <span className="text-warning text-[16px] mt-0.5">&#9888;</span>
            <div className="text-[13px] text-warning">
              <span className="font-semibold">보유 종목 {positions.length}개가 유지됩니다</span>
              <p className="mt-1 text-warning/80">봇을 중지해도 보유 종목은 자동으로 매도되지 않습니다. 필요 시 수동으로 청산하세요.</p>
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

        {/* 보유종목 테이블 */}
        {hasPositions && (
          <div className="mb-4">
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
        )}

        {/* 체결 대기 */}
        {hasPendingOrders && (
          <div className="mb-4">
            <h3 className="text-[13px] font-semibold text-text-muted mb-2">체결 대기</h3>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[12px]">
                <thead>
                  <tr>
                    <th className="text-left px-2 py-1.5 font-semibold text-text-muted border-b border-border">종목</th>
                    <th className="text-center px-2 py-1.5 font-semibold text-text-muted border-b border-border">유형</th>
                    <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-b border-border">수량</th>
                    <th className="text-right px-2 py-1.5 font-semibold text-text-muted border-b border-border">주문가</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingOrders.map((order, i) => (
                    <tr key={`${order.symbol}-${i}`}>
                      <td className="px-2 py-1.5 font-mono border-b border-border/50">{order.symbol}</td>
                      <td className={`text-center px-2 py-1.5 border-b border-border/50 ${order.side === 'buy' ? 'text-positive' : 'text-negative'}`}>
                        {order.side === 'buy' ? '매수' : '매도'}
                      </td>
                      <td className="text-right px-2 py-1.5 border-b border-border/50">{order.quantity.toLocaleString()}</td>
                      <td className="text-right px-2 py-1.5 border-b border-border/50">{order.price.toLocaleString()}원</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
            onClick={onConfirm}
            disabled={isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative/80 disabled:opacity-50"
          >
            {isPending ? '중지 중...' : '중지'}
          </button>
        </div>
      </div>
    </div>
  )
}
