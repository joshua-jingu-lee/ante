import client from './client'
import type {
  ApprovalDetailResponse as ApiApprovalDetailResponse,
  ApprovalItem as ApiApprovalItem,
  ApprovalListResponse as ApiApprovalListResponse,
  ApprovalStatusUpdate as ApiApprovalStatusUpdate,
  ApprovalUpdateResponse as ApiApprovalUpdateResponse,
} from '../types/api.generated'
import {
  isApprovalType,
  type Approval,
  type ApprovalDetail,
  type ApprovalHistoryEntry,
  type ApprovalListView,
  type ApprovalReview,
  type ApprovalStatus,
  type ApprovalType,
  type ApprovalTypeRef,
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

/**
 * raw API ``type`` 문자열을 UI 모델 ``ApprovalTypeRef`` 로 변환한다 (#1471 —
 * split #1418/C).
 *
 * backend SSOT 인 ``ApprovalType`` enum (``src/ante/approval/models.py``) 에
 * 없는 값은 silent fallback 으로 known type 로 변환되지 않는다. 대신
 * ``kind: 'unknown'`` branch 로 분기해 raw 문자열을 그대로 보존하고,
 * operator 가 인지할 수 있도록 ``console.warn`` 으로 알린다. legacy invalid
 * row 또는 contract drift 진단 경로다.
 */
function toApprovalTypeRef(value: string): ApprovalTypeRef {
  if (isApprovalType(value)) {
    return { kind: 'known', value }
  }
  // legacy invalid row 또는 contract drift 진단용. silent fallback 금지.
  console.warn(
    `[approvals] unknown approval type "${value}" — backend SSOT (ApprovalType) 에 없는 값입니다. legacy invalid row 또는 contract drift 가능성.`,
  )
  return { kind: 'unknown', raw: value }
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
    type: toApprovalTypeRef(raw.type),
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
