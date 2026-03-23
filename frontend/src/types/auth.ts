/**
 * Auth 도메인 타입.
 *
 * API 응답 타입은 api.generated.ts에서 자동 생성된 타입을 사용한다.
 * 프론트엔드 전용 타입만 이 파일에 직접 정의한다.
 */
import type {
  LoginRequest as GeneratedLoginRequest,
  LoginResponse as GeneratedLoginResponse,
  MeResponse,
} from './api.generated'

// ── API 응답 타입 re-export ──────────────────────────────
export type LoginRequest = GeneratedLoginRequest
export type LoginResponse = GeneratedLoginResponse

// ── 프론트엔드 전용 타입 ──────────────────────────────────

/** /api/auth/me 응답 — generated MeResponse에 scopes, org 필드 추가 */
export interface User extends MeResponse {
  org: string
  scopes: string[]
}
