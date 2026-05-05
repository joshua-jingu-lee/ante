/**
 * Auth 도메인 타입.
 *
 * API 계약 타입은 frontend/src/api/auth.ts 어댑터 안에서만 사용한다.
 * 이 파일은 화면과 훅이 공유하는 프론트엔드 전용 타입만 노출한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────

export interface LoginInput {
  member_id: string
  password: string
}

export interface LoginResultView {
  member_id: string
  name: string
  type: string
}

export interface AuthUserView {
  member_id: string
  name: string
  type: string
  role: string
  emoji?: string
  login_at?: string
  scopes: string[]
}

export type User = AuthUserView
