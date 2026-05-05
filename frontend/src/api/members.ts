import client from './client'
import type {
  MemberCreateRequest as ApiMemberCreateRequest,
  MemberCreateResponse as ApiMemberCreateResponse,
  MemberDetailResponse as ApiMemberDetailResponse,
  MemberInfo as ApiMemberInfo,
  MemberListResponse as ApiMemberListResponse,
  MemberScopesResponse as ApiMemberScopesResponse,
  MemberTokenResponse as ApiMemberTokenResponse,
  OkResponse as ApiOkResponse,
  PasswordChangeRequest as ApiPasswordChangeRequest,
  ScopesUpdateRequest as ApiScopesUpdateRequest,
} from '../types/api.generated'
import type {
  HumanRole,
  Member,
  MemberCreateInput,
  MemberDetail,
  MemberStatus,
  MemberTokenView,
  MemberType,
} from '../types/member'

function toMemberType(value: string): MemberType {
  return value === 'human' ? 'human' : 'agent'
}

function toMemberStatus(value: string): MemberStatus {
  if (value === 'suspended' || value === 'revoked') return value
  return 'active'
}

function toHumanRole(value: string): HumanRole | undefined {
  if (value === 'owner' || value === 'master' || value === 'admin') return value
  return undefined
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

export function toMemberView(raw: ApiMemberInfo): Member {
  return {
    member_id: raw.member_id,
    name: raw.name,
    type: toMemberType(raw.type),
    org: raw.org,
    emoji: raw.emoji || undefined,
    role: toHumanRole(raw.role),
    status: toMemberStatus(raw.status),
    scopes: raw.scopes,
    last_active_at: raw.last_active_at || undefined,
    created_at: raw.created_at,
  }
}

export function toMemberDetailView(raw: ApiMemberInfo): MemberDetail {
  return {
    ...toMemberView(raw),
    scopes: raw.scopes,
    created_by: raw.created_by || undefined,
    token_prefix: toOptionalString(raw.token_prefix),
    suspended_at: raw.suspended_at || undefined,
  }
}

function toMemberTokenView(raw: ApiMemberCreateResponse | ApiMemberTokenResponse): MemberTokenView {
  return {
    member: toMemberDetailView(raw.member),
    token: raw.token,
  }
}

export async function getMembers(params?: {
  type?: string
  org?: string
  status?: string
}): Promise<Member[]> {
  const res = await client.get<ApiMemberListResponse>('/api/members', { params })
  return res.data.members.map(toMemberView)
}

export async function getMemberDetail(id: string): Promise<MemberDetail> {
  const res = await client.get<ApiMemberDetailResponse>(`/api/members/${id}`)
  return toMemberDetailView(res.data.member)
}

export async function createMember(data: MemberCreateInput): Promise<MemberTokenView> {
  const payload: ApiMemberCreateRequest = {
    ...data,
    role: data.role ?? 'default',
  }
  const res = await client.post<ApiMemberCreateResponse>('/api/members', payload)
  return toMemberTokenView(res.data)
}

export async function suspendMember(id: string): Promise<void> {
  await client.post<ApiMemberDetailResponse>(`/api/members/${id}/suspend`)
}

export async function reactivateMember(id: string): Promise<void> {
  await client.post<ApiMemberDetailResponse>(`/api/members/${id}/reactivate`)
}

export async function revokeMember(id: string): Promise<void> {
  await client.post<ApiMemberDetailResponse>(`/api/members/${id}/revoke`)
}

export async function rotateToken(id: string): Promise<MemberTokenView> {
  const res = await client.post<ApiMemberTokenResponse>(`/api/members/${id}/rotate-token`)
  return toMemberTokenView(res.data)
}

export async function changePassword(id: string, oldPassword: string, newPassword: string): Promise<void> {
  const payload: ApiPasswordChangeRequest = { old_password: oldPassword, new_password: newPassword }
  await client.patch<ApiOkResponse>(`/api/members/${id}/password`, payload)
}

export async function updateScopes(id: string, scopes: string[]): Promise<void> {
  const payload: ApiScopesUpdateRequest = { scopes }
  await client.put<ApiMemberScopesResponse>(`/api/members/${id}/scopes`, payload)
}

export async function updateMemberInfo(id: string, data: { name: string; org: string }): Promise<void> {
  await client.patch<ApiMemberDetailResponse>(`/api/members/${id}`, data)
}
