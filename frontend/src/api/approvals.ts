import client from './client'
import type {
  ApprovalDetailResponse as ApiApprovalDetailResponse,
  ApprovalItem as ApiApprovalItem,
  ApprovalListResponse as ApiApprovalListResponse,
  ApprovalStatusUpdate as ApiApprovalStatusUpdate,
  ApprovalUpdateResponse as ApiApprovalUpdateResponse,
} from '../types/api.generated'
import type {
  Approval,
  ApprovalDetail,
  ApprovalDisplayType,
  ApprovalHistoryEntry,
  ApprovalListView,
  ApprovalReview,
  ApprovalStatus,
  ApprovalType,
} from '../types/approval'

interface ApprovalsParams {
  status?: ApprovalStatus | 'all'
  type?: ApprovalType | 'all'
  search?: string
  offset?: number
  limit?: number
}

function toRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function toApprovalStatus(value: string): ApprovalStatus {
  if (value === 'approved' || value === 'rejected') return value
  return 'pending'
}

function toApprovalType(value: string): ApprovalDisplayType {
  if (
    value === 'strategy_report'
    || value === 'budget_allocate'
    || value === 'live_switch'
    || value === 'risk_alert'
    || value === 'strategy_adopt'
    || value === 'budget_change'
    || value === 'bot_create'
    || value === 'bot_stop'
    || value === 'rule_change'
    || value === 'strategy_retire'
    || value === 'bot_assign_strategy'
    || value === 'bot_change_strategy'
    || value === 'bot_resume'
    || value === 'bot_delete'
  ) {
    return value
  }
  return 'unknown'
}

function toReviewResult(value: unknown): ApprovalReview['result'] {
  if (value === 'pass' || value === 'fail') return value
  return 'warn'
}

function toApprovalReview(value: unknown): ApprovalReview {
  const row = toRecord(value)
  return {
    reviewer: toString(row.reviewer),
    result: toReviewResult(row.result),
    detail: toString(row.detail),
    reviewed_at: toString(row.reviewed_at),
  }
}

function toApprovalHistoryEntry(value: unknown): ApprovalHistoryEntry {
  const row = toRecord(value)
  return {
    action: toString(row.action),
    actor: toString(row.actor),
    at: toString(row.at),
    detail: toOptionalString(row.detail),
  }
}

function toApproval(raw: ApiApprovalItem): Approval {
  return {
    id: raw.id,
    type: toApprovalType(raw.type),
    title: raw.title,
    requester: raw.requester,
    requested_at: toString(raw.created_at),
    status: toApprovalStatus(raw.status),
    reference_id: toOptionalString(raw.reference_id),
    memo: toOptionalString(raw.memo),
    resolved_at: toOptionalString(raw.resolved_at),
    resolved_by: toOptionalString(raw.resolved_by),
    body: toOptionalString(raw.body),
    params: raw.params,
    reviews: raw.reviews.map(toApprovalReview),
    history: raw.history.map(toApprovalHistoryEntry),
    expires_at: toOptionalString(raw.expires_at),
    reject_reason: toOptionalString(raw.reject_reason),
  }
}

export async function getApprovals(params: ApprovalsParams): Promise<ApprovalListView> {
  const query: Record<string, string | number> = {}
  if (params.status && params.status !== 'all') query.status = params.status
  if (params.type && params.type !== 'all') query.type = params.type
  if (params.search) query.search = params.search
  if (params.offset) query.offset = params.offset
  if (params.limit) query.limit = params.limit
  const res = await client.get<ApiApprovalListResponse>('/api/approvals', { params: query })
  return {
    items: res.data.approvals.map(toApproval),
    total: res.data.total,
  }
}

export async function getApprovalDetail(id: string): Promise<ApprovalDetail> {
  const res = await client.get<ApiApprovalDetailResponse>(`/api/approvals/${id}`)
  return toApproval(res.data.approval)
}

export async function updateApprovalStatus(
  id: string,
  status: 'approved' | 'rejected',
  memo?: string,
): Promise<void> {
  const payload: ApiApprovalStatusUpdate = { status, memo: memo ?? '' }
  await client.patch<ApiApprovalUpdateResponse>(`/api/approvals/${id}/status`, payload)
}
