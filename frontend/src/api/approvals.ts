import client from './client'
import type { Approval, ApprovalDetail, ApprovalStatus, ApprovalType } from '../types/approval'

interface ApprovalsParams {
  status?: ApprovalStatus | 'all'
  type?: ApprovalType | 'all'
  offset?: number
  limit?: number
}

interface ApprovalsResponse {
  items: Approval[]
  total: number
}

export async function getApprovals(params: ApprovalsParams): Promise<ApprovalsResponse> {
  const query: Record<string, string | number> = {}
  if (params.status && params.status !== 'all') query.status = params.status
  if (params.type && params.type !== 'all') query.type = params.type
  if (params.offset) query.offset = params.offset
  if (params.limit) query.limit = params.limit
  const res = await client.get('/api/approvals', { params: query })
  const data = res.data
  return {
    items: data.approvals ?? data.items ?? [],
    total: data.total ?? (data.approvals ?? data.items ?? []).length,
  }
}

export async function getApprovalDetail(id: string): Promise<ApprovalDetail> {
  const res = await client.get(`/api/approvals/${id}`)
  return res.data.approval ?? res.data
}

export async function updateApprovalStatus(
  id: string,
  status: 'approved' | 'rejected',
  memo?: string,
): Promise<void> {
  await client.patch(`/api/approvals/${id}/status`, { status, memo })
}
