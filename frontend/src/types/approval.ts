/**
 * Approval 도메인 타입.
 *
 * 백엔드가 dict 기반(extra="allow") 응답을 반환하므로
 * 프론트엔드에서 상세 필드를 명시적으로 정의한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'
export type ApprovalType =
  | 'strategy_report'
  | 'budget_allocate'
  | 'live_switch'
  | 'risk_alert'
  | 'strategy_adopt'
  | 'budget_change'
  | 'bot_create'
  | 'bot_stop'
  | 'rule_change'

export interface ApprovalReview {
  reviewer: string
  result: 'pass' | 'warn' | 'fail'
  detail: string
  reviewed_at: string
}

export interface ApprovalHistoryEntry {
  action: string
  actor: string
  at: string
  detail?: string
}

export interface Approval {
  id: string
  type: ApprovalType
  title: string
  requester: string
  requested_at: string
  status: ApprovalStatus
  reference_id?: string
  memo?: string
  resolved_at?: string
  resolved_by?: string
  body?: string
  params?: Record<string, unknown>
  reviews?: ApprovalReview[]
  history?: ApprovalHistoryEntry[]
  expires_at?: string
  reject_reason?: string
}

export type ApprovalDetail = Approval
