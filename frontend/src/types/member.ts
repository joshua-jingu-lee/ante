export type MemberStatus = 'active' | 'suspended' | 'revoked'
export type MemberType = 'human' | 'agent'

export interface Member {
  member_id: string
  name: string
  type: MemberType
  org: string
  status: MemberStatus
  last_active_at?: string
  created_at: string
}

export interface MemberDetail extends Member {
  scopes: string[]
  created_by?: string
}

export interface MemberCreateRequest {
  member_id: string
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
