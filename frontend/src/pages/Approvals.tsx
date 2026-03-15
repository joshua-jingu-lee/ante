import { useState } from 'react'
import { useApprovals } from '../hooks/useApprovals'
import ApprovalFilters from '../components/approvals/ApprovalFilters'
import ApprovalTable from '../components/approvals/ApprovalTable'
import Pagination from '../components/common/Pagination'
import LoadingSpinner from '../components/common/LoadingSpinner'
import type { ApprovalStatus, ApprovalType } from '../types/approval'

const LIMIT = 20

export default function Approvals() {
  const [status, setStatus] = useState<ApprovalStatus | 'all'>('all')
  const [type, setType] = useState<ApprovalType | 'all'>('all')
  const [offset, setOffset] = useState(0)

  const { data, isLoading } = useApprovals({ status, type, offset, limit: LIMIT })

  return (
    <>
      <ApprovalFilters
        status={status}
        type={type}
        onStatusChange={(s) => { setStatus(s); setOffset(0) }}
        onTypeChange={(t) => { setType(t); setOffset(0) }}
      />
      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <LoadingSpinner />
        ) : (
          <>
            <ApprovalTable items={data?.items ?? []} />
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
