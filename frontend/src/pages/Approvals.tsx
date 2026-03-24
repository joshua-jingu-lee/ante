import { useState } from 'react'
import { useApprovals } from '../hooks/useApprovals'
import ApprovalFilters from '../components/approvals/ApprovalFilters'
import ApprovalTable from '../components/approvals/ApprovalTable'
import Pagination from '../components/common/Pagination'
import { TableSkeleton } from '../components/common/Skeleton'
import type { ApprovalStatus, ApprovalType } from '../types/approval'

const LIMIT = 20

export default function Approvals() {
  const [status, setStatus] = useState<ApprovalStatus | 'all'>('all')
  const [type, setType] = useState<ApprovalType | 'all'>('all')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)

  const { data, isLoading } = useApprovals({ status, type, search: search || undefined, offset, limit: LIMIT })
  const pendingQuery = useApprovals({ status: 'pending', limit: 0 })

  const allItems = data?.items ?? []

  return (
    <>
      <ApprovalFilters
        status={status}
        type={type}
        search={search}
        pendingCount={pendingQuery.data?.total ?? 0}
        onStatusChange={(s) => { setStatus(s); setOffset(0) }}
        onTypeChange={(t) => { setType(t); setOffset(0) }}
        onSearchChange={(q) => { setSearch(q); setOffset(0) }}
      />
      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <TableSkeleton rows={5} cols={6} />
        ) : (
          <>
            <ApprovalTable items={allItems} />
            {(data?.total ?? 0) > LIMIT && (
              <Pagination
                total={data?.total ?? 0}
                offset={offset}
                limit={LIMIT}
                onPageChange={setOffset}
              />
            )}
          </>
        )}
      </div>
    </>
  )
}
