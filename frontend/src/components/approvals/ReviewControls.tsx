import { useState } from 'react'
import { useUpdateApprovalStatus } from '../../hooks/useApprovals'

export default function ReviewControls({ approvalId, isPending }: { approvalId: number; isPending: boolean }) {
  const [memo, setMemo] = useState('')
  const updateStatus = useUpdateApprovalStatus()

  if (!isPending) return null

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-3">결재</h3>
      <textarea
        value={memo}
        onChange={(e) => setMemo(e.target.value)}
        placeholder="메모 (선택)"
        rows={3}
        className="w-full bg-bg border border-border rounded-lg p-3 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary resize-vertical mb-3"
      />
      <div className="flex gap-2">
        <button
          onClick={() => updateStatus.mutate({ id: approvalId, status: 'approved', memo: memo || undefined })}
          disabled={updateStatus.isPending}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover disabled:opacity-50"
        >
          승인
        </button>
        <button
          onClick={() => updateStatus.mutate({ id: approvalId, status: 'rejected', memo: memo || undefined })}
          disabled={updateStatus.isPending}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative-hover disabled:opacity-50"
        >
          거부
        </button>
      </div>
    </div>
  )
}
