/**
 * Member 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/members.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type MemberStatus = 'active' | 'suspended' | 'revoked'
export type MemberType = 'human' | 'agent'
export type HumanRole = 'owner' | 'master' | 'admin'

export interface MemberView {
  member_id: string
  name: string
  type: MemberType
  org: string
  emoji?: string
  role?: HumanRole
  status: MemberStatus
  scopes?: string[]
  last_active_at?: string
  created_at: string
}

export interface MemberDetailView extends MemberView {
  scopes: string[]
  created_by?: string
  token_prefix?: string
  suspended_at?: string
}

export interface MemberCreateInput {
  member_id: string
  member_type: MemberType
  name: string
  org: string
  role?: HumanRole | 'default'
  scopes: string[]
}

export interface MemberTokenView {
  member: MemberDetailView
  token: string
}

export type Member = MemberView
export type MemberDetail = MemberDetailView

export const ALL_SCOPES = [
  'strategy:read',
  'strategy:write',
  'report:write',
  'approval:write',
  'approval:read',
  'bot:read',
  'data:read',
  'data:write',
  'backtest:run',
] as const
