/**
 * Approval 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/approvals.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

/**
 * 결재 유형. backend ``ApprovalType`` enum SSOT 와 정확히 일치한다 (#1471 — split
 * #1418/C). SSOT: ``src/ante/approval/models.py:ApprovalType``.
 *
 * - ``strategy_adopt`` / ``strategy_retire``: 전략 채택/은퇴
 * - ``bot_create`` / ``bot_assign_strategy`` / ``bot_change_strategy``
 *   / ``bot_stop`` / ``bot_resume`` / ``bot_delete``: 봇 라이프사이클
 * - ``budget_change`` / ``rule_change``: 예산/룰 변경
 *
 * SSOT 에 정의되지 않은 값(legacy invalid row, contract drift)은 어댑터에서
 * ``ApprovalTypeRef.kind === 'unknown'`` branch 로 명시적으로 분기되며,
 * silent fallback (예: 과거의 ``strategy_report``) 으로 잘못 라벨링되지 않는다.
 */
export const APPROVAL_TYPES = [
  'strategy_adopt',
  'strategy_retire',
  'bot_create',
  'bot_assign_strategy',
  'bot_change_strategy',
  'bot_stop',
  'bot_resume',
  'bot_delete',
  'budget_change',
  'rule_change',
] as const
export type ApprovalType = typeof APPROVAL_TYPES[number]

export function isApprovalType(value: string): value is ApprovalType {
  return (APPROVAL_TYPES as readonly string[]).includes(value)
}

/**
 * UI 가 다루는 결재 유형 참조.
 *
 * ``kind: 'known'`` 인 경우 SSOT enum 값으로 정상 표시한다. ``kind: 'unknown'``
 * 은 legacy invalid row 또는 backend ↔ frontend contract drift 로 SSOT 에
 * 없는 type 이 들어왔음을 의미한다 — operator 가 인지할 수 있도록 명시적으로
 * 표시하며, 알려진 유형으로 silent fallback 하지 않는다.
 */
export type ApprovalTypeRef =
  | { kind: 'known'; value: ApprovalType }
  | { kind: 'unknown'; raw: string }

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
  type: ApprovalTypeRef
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
