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
  'approval:create',
  'approval:review',
  'bot:read',
  'data:read',
  'data:write',
  'backtest:run',
] as const
