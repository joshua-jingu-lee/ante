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
  ApiMemberRole,
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

/**
 * Backend ``MemberInfo.role`` 을 display 용 {@link HumanRole} 로 변환한다.
 *
 * - ``master`` / ``admin`` 은 동일 이름으로 매핑된다.
 * - ``default`` 는 display 측에서 role 뱃지를 표시하지 않으므로 ``undefined`` 로
 *   매핑한다.
 * - ``owner`` 는 backend ``MemberRole`` enum 에 존재하지 않지만, 과거 데이터나
 *   legacy admin 도구가 ``owner`` 로 기록한 경우 ``undefined`` 로 정규화하고
 *   display sentinel 은 ``member_id === 'owner'`` 기반 derive 에서 채운다
 *   (#1467 — split #1417/C). 어떤 경우에도 backend 응답의 ``owner`` 를 그대로
 *   ``HumanRole`` 로 노출하지 않는다.
 */
function toDisplayRole(value: string, memberId: string): HumanRole | undefined {
  if (memberId === 'owner') return 'owner'
  if (value === 'master' || value === 'admin') return value
  return undefined
}

/**
 * 호출부에서 받은 {@link MemberCreateInput.role} 을 API payload 용
 * {@link ApiMemberRole} 로 정규화한다. ``MemberCreateInput.role`` 의 타입이
 * 이미 ``ApiMemberRole | undefined`` 이므로 ``owner`` 는 컴파일 단계에서
 * 차단되지만, ``default`` 누락 시 명시적으로 채워 generated
 * ``MemberCreateRequest.role`` 의 required invariant 를 만족시킨다.
 */
function toApiMemberRole(role: ApiMemberRole | undefined): ApiMemberRole {
  return role ?? 'default'
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
    role: toDisplayRole(raw.role, raw.member_id),
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
  // `MemberCreateInput.role` 은 `ApiMemberRole` 로 좁혀져 있으므로 display
  // sentinel `owner` 가 들어올 수 없다 (#1467 — split #1417/C). undefined 일
  // 때만 백엔드 default 와 동일한 'default' 로 명시 채움.
  const payload: ApiMemberCreateRequest = {
    ...data,
    role: toApiMemberRole(data.role),
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
