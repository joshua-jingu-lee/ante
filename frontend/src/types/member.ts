/**
 * Member 도메인 타입.
 *
 * 백엔드가 dict 기반(extra="allow") 응답을 반환하므로
 * 프론트엔드에서 상세 필드를 명시적으로 정의한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type MemberStatus = 'active' | 'suspended' | 'revoked'
export type MemberType = 'human' | 'agent'
export type HumanRole = 'owner' | 'master' | 'admin'

export interface Member {
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

export interface MemberDetail extends Member {
  scopes: string[]
  created_by?: string
  token_prefix?: string
  suspended_at?: string
}

export interface MemberCreateRequest {
  member_id: string
  member_type: MemberType
  name: string
  org: string
  scopes: string[]
}

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
