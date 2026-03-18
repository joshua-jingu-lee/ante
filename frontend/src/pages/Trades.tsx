import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useStrategyTradesPaginated } from '../hooks/useStrategies'
import { PageSkeleton } from '../components/common/Skeleton'
import StatusBadge from '../components/common/StatusBadge'
import Pagination from '../components/common/Pagination'
import { formatKRW, formatDateTime } from '../utils/formatters'

const PAGE_SIZE = 15

export default function Trades() {
  const { id = '' } = useParams<{ id: string }>()
  const [offset, setOffset] = useState(0)
  const [sideFilter, setSideFilter] = useState<string>('')

  const { data, isLoading } = useStrategyTradesPaginated(id, {
    offset,
    limit: PAGE_SIZE,
    side: sideFilter || undefined,
  })

  if (isLoading && !data) return <PageSkeleton />

  const trades = data?.items ?? []
  const total = data?.total ?? 0

  return (
    <>
      {/* 헤더 */}
      <div className="flex items-center gap-3 mb-6">
        <Link
          to={`/strategies/${id}`}
          className="text-[13px] text-text-muted no-underline hover:text-text"
        >
          &larr; 전략 상세
        </Link>
        <h2 className="text-[20px] font-bold">거래 내역</h2>
      </div>

      {/* 필터 바 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center gap-4 flex-wrap">
          <div>
            <label className="text-[12px] text-text-muted block mb-1">매매</label>
            <select
              value={sideFilter}
              onChange={(e) => {
                setSideFilter(e.target.value)
                setOffset(0)
              }}
              className="h-8 px-3 rounded-lg border border-border bg-bg text-[13px] text-text"
            >
              <option value="">전체</option>
              <option value="buy">매수</option>
              <option value="sell">매도</option>
            </select>
          </div>
        </div>
      </div>

      {/* 거래 테이블 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">시각</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">종목</th>
                <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">매매</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">수량</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">단가</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">금액</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">수수료</th>
                <th className="text-right px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">손익</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-text-muted text-[13px]">
                    거래 내역이 없습니다
                  </td>
                </tr>
              ) : (
                trades.map((t) => {
                  const amount = t.quantity * t.price
                  const displayName = t.symbol_name
                    ? `${t.symbol_name} (${t.symbol})`
                    : t.symbol

                  return (
                    <tr key={t.id} className="hover:bg-surface-hover">
                      <td className="px-3 py-2.5 border-b border-border text-[13px] font-mono">
                        {formatDateTime(t.executed_at)}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px]">
                        {displayName}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px]">
                        <StatusBadge variant={t.side === 'buy' ? 'negative' : 'positive'}>
                          {t.side === 'buy' ? '매수' : '매도'}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                        {t.quantity.toLocaleString()}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                        {formatKRW(t.price)}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                        {formatKRW(amount)}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right text-text-muted">
                        {t.commission != null ? formatKRW(t.commission) : '-'}
                      </td>
                      <td className="px-3 py-2.5 border-b border-border text-[13px] text-right">
                        {t.pnl != null ? (
                          <span className={t.pnl >= 0 ? 'text-positive' : 'text-negative'}>
                            {formatKRW(t.pnl)}
                          </span>
                        ) : (
                          <span className="text-text-muted">&mdash;</span>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {total > PAGE_SIZE && (
          <Pagination
            total={total}
            offset={offset}
            limit={PAGE_SIZE}
            onPageChange={setOffset}
          />
        )}
      </div>
    </>
  )
}
