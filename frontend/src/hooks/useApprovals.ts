import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getApprovals, getApprovalDetail, updateApprovalStatus } from '../api/approvals'
import type { ApprovalStatus, ApprovalType } from '../types/approval'

export function useApprovals(params: {
  status?: ApprovalStatus | 'all'
  type?: ApprovalType | 'all'
  offset?: number
  limit?: number
}) {
  return useQuery({
    queryKey: ['approvals', params],
    queryFn: () => getApprovals(params),
  })
}

export function useApprovalDetail(id: string) {
  return useQuery({
    queryKey: ['approvals', id],
    queryFn: () => getApprovalDetail(id),
    enabled: !!id,
  })
}

export function useUpdateApprovalStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, memo }: { id: string; status: 'approved' | 'rejected'; memo?: string }) =>
      updateApprovalStatus(id, status, memo),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}
