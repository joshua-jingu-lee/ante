export type ApprovalStatus = 'pending' | 'approved' | 'rejected'
export type ApprovalType = 'strategy_adopt' | 'budget_change' | 'bot_create' | 'bot_stop' | 'rule_change'

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
