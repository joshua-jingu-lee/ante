/**
 * Member 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/members.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type MemberStatus = 'active' | 'suspended' | 'revoked'
export type MemberType = 'human' | 'agent'

/**
 * UI display 전용 human role.
 *
 * - ``owner`` 는 ``member_id === 'owner'`` 로 derive 되는 display sentinel 이다.
 *   백엔드 `MemberRole` enum 에는 존재하지 않으므로 API payload 로는 절대
 *   전송되어선 안 된다 (#1467 — split #1417/C).
 * - ``master`` / ``admin`` 은 backend role 과 1:1 매핑된다.
 * - backend role 이 ``default`` 인 경우 display 측에서는 role 뱃지를 표시하지
 *   않으므로 ``HumanRole`` 에 포함시키지 않고 ``MemberView.role`` 을
 *   ``undefined`` 로 채운다.
 *
 * **payload 용도로는 절대 사용하지 말 것.** payload 는 ``ApiMemberRole`` 을
 * 사용한다.
 */
export type HumanRole = 'owner' | 'master' | 'admin'

/**
 * API payload 용 member role.
 *
 * generated ``MemberCreateRequest.role`` 과 동일한 vocabulary (#1465, SSOT:
 * ``src/ante/member/models.py`` ``MemberRole``). display sentinel ``owner`` 는
 * 의도적으로 배제되어 컴파일 시점에 payload 전송이 차단된다.
 *
 * `MemberCreateRequest.role` 이 좁혀진 후, payload 자리에 ``owner`` 가 섞이지
 * 않게 하는 SSOT 다 — adapter 와 hooks 는 이 타입만 사용해야 한다.
 */
export type ApiMemberRole = 'master' | 'admin' | 'default'

/**
 * `MemberCreateInput.role` 에 사용하는 별칭. ``ApiMemberRole`` 과 동일하며,
 * 호출부에서 의미를 명확히 하기 위해 별도 이름을 유지한다.
 *
 * @deprecated 새 코드는 {@link ApiMemberRole} 을 직접 사용한다. 기존 호출부
 *   호환을 위해 별칭만 남긴다.
 */
export type MemberCreateRole = ApiMemberRole

export interface MemberView {
  member_id: string
  name: string
  type: MemberType
  org: string
  emoji?: string
  /**
   * Display 전용 human role. ``HumanRole | undefined`` 이며 payload 로 전송하지
   * 않는다. backend ``default`` 는 ``undefined`` 로 매핑되고, ``owner`` 는
   * ``member_id === 'owner'`` 인 경우 adapter 가 derive 한다.
   */
  role?: HumanRole
  status: MemberStatus
  scopes?: string[]
  last_active_at?: string
  created_at: string
}

export interface MemberDetailView extends MemberView {
  scopes: string[]
  created_by?: string
  suspended_at?: string
}

/**
 * POST /api/members 요청 body 의 ``role`` 은 {@link ApiMemberRole} 만 허용한다
 * (#1465, #1467 — split #1417/A·C). display sentinel ``owner`` 는 타입 차원에서
 * 배제되어, ``createMember()`` 호출부에서 owner role 을 payload 로 보낼 수 없다.
 */
export interface MemberCreateInput {
  member_id: string
  member_type: MemberType
  name: string
  org: string
  role?: ApiMemberRole
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
