import client from './client'
import type { Approval, ApprovalDetail, ApprovalStatus, ApprovalType } from '../types/approval'

interface ApprovalsParams {
  status?: ApprovalStatus | 'all'
  type?: ApprovalType | 'all'
  search?: string
  offset?: number
  limit?: number
}

interface ApprovalsResponse {
  items: Approval[]
  total: number
}

/** API 응답의 created_at을 프론트엔드 타입의 requested_at으로 매핑 */
function mapApproval<T extends Record<string, unknown>>(raw: T): T & { requested_at: string } {
  const mapped = { ...raw } as T & { requested_at: string }
  if (!mapped.requested_at && (raw as Record<string, unknown>).created_at) {
    mapped.requested_at = (raw as Record<string, unknown>).created_at as string
  }
  return mapped
}

export async function getApprovals(params: ApprovalsParams): Promise<ApprovalsResponse> {
  const query: Record<string, string | number> = {}
  if (params.status && params.status !== 'all') query.status = params.status
  if (params.type && params.type !== 'all') query.type = params.type
  if (params.search) query.search = params.search
  if (params.offset) query.offset = params.offset
  if (params.limit) query.limit = params.limit
  const res = await client.get('/api/approvals', { params: query })
  const data = res.data
  const rawItems = data.approvals ?? data.items ?? []
  return {
    items: rawItems.map(mapApproval),
    total: data.total ?? rawItems.length,
  }
}

export async function getApprovalDetail(id: string): Promise<ApprovalDetail> {
  const res = await client.get(`/api/approvals/${id}`)
  const raw = res.data.approval ?? res.data
  return mapApproval(raw)
}

export async function updateApprovalStatus(
  id: string,
  status: 'approved' | 'rejected',
  memo?: string,
): Promise<void> {
  await client.patch(`/api/approvals/${id}/status`, { status, memo })
}
