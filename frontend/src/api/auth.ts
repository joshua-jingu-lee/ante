import client from './client'
import type {
  LoginRequest as ApiLoginRequest,
  LoginResponse as ApiLoginResponse,
  LogoutResponse as ApiLogoutResponse,
  MeResponse as ApiMeResponse,
} from '../types/api.generated'
import type { AuthUserView, LoginInput, LoginResultView } from '../types/auth'

export function toLoginResultView(raw: ApiLoginResponse): LoginResultView {
  return {
    member_id: raw.member_id,
    name: raw.name,
    type: raw.type,
  }
}

export function toAuthUserView(raw: ApiMeResponse): AuthUserView {
  return {
    member_id: raw.member_id,
    name: raw.name,
    type: raw.type,
    role: raw.role,
    emoji: raw.emoji || undefined,
    login_at: raw.login_at || undefined,
    scopes: [],
  }
}

export async function login(data: LoginInput): Promise<LoginResultView> {
  const payload: ApiLoginRequest = data
  const res = await client.post<ApiLoginResponse>('/api/auth/login', payload)
  return toLoginResultView(res.data)
}

export async function logout(): Promise<void> {
  await client.post<ApiLogoutResponse>('/api/auth/logout')
}

export async function getMe(): Promise<AuthUserView> {
  const res = await client.get<ApiMeResponse>('/api/auth/me')
  return toAuthUserView(res.data)
}
