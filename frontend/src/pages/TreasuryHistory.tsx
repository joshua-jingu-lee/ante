import { useState } from 'react'
import { useTreasuryHistory } from '../hooks/useTreasury'
import { formatKRW, formatDateTime } from '../utils/formatters'
import Pagination from '../components/common/Pagination'
import { TableSkeleton } from '../components/common/Skeleton'

const LIMIT = 20

export default function TreasuryHistory() {
  const [offset, setOffset] = useState(0)
  const { data, isLoading } = useTreasuryHistory(offset, LIMIT)

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-4">자금 거래 이력</h3>
      {isLoading ? (
        <TableSkeleton rows={5} cols={5} />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">유형</th>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">봇 ID</th>
                  <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">금액</th>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">설명</th>
                  <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">일시</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).length === 0 ? (
                  <tr><td colSpan={5} className="px-3 py-8 text-center text-text-muted text-[13px]">이력이 없습니다</td></tr>
                ) : (
                  (data?.items ?? []).map((tx) => (
                    <tr key={tx.id} className="hover:bg-surface-hover">
                      <td className="px-3 py-3 border-b border-border text-[13px]">{tx.type}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px] font-mono">{tx.bot_id || '-'}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-right">{formatKRW(tx.amount)}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px]">{tx.description}</td>
                      <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{formatDateTime(tx.created_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {(data?.total ?? 0) > LIMIT && (
            <Pagination total={data?.total ?? 0} offset={offset} limit={LIMIT} onPageChange={setOffset} />
          )}
        </>
      )}
    </div>
  )
}
