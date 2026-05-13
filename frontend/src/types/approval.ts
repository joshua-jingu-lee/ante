/**
 * Approval 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/approvals.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
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
  | 'strategy_retire'
  | 'bot_assign_strategy'
  | 'bot_change_strategy'
  | 'bot_resume'
  | 'bot_delete'

/**
 * UI 표시용 ApprovalType.
 * adapter가 백엔드의 알 수 없는 type 값을 'unknown'으로 매핑하면
 * UI는 별도의 fallback 렌더링 경로를 거친다.
 */
export type ApprovalDisplayType = ApprovalType | 'unknown'

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
  type: ApprovalDisplayType
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

export interface ApprovalListView {
  items: Approval[]
  total: number
}
