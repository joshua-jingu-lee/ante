import { useUpdateApprovalStatus } from '../../hooks/useApprovals'

export default function ReviewControls({ approvalId, isPending }: { approvalId: string; isPending: boolean }) {
  const updateStatus = useUpdateApprovalStatus()

  if (!isPending) return null

  return (
    <div className="flex gap-2">
      <button
        onClick={() => updateStatus.mutate({ id: approvalId, status: 'rejected' })}
        disabled={updateStatus.isPending}
        className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text border border-border cursor-pointer hover:bg-surface-hover disabled:opacity-50"
      >
        거부
      </button>
      <button
        onClick={() => updateStatus.mutate({ id: approvalId, status: 'approved' })}
        disabled={updateStatus.isPending}
        className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover disabled:opacity-50"
      >
        승인
      </button>
    </div>
  )
}
