export interface LoginRequest {
  member_id: string
  password: string
}

export interface User {
  member_id: string
  name: string
  role: string
  type: string
  org: string
  scopes: string[]
  emoji: string
  login_at: string
}

export interface LoginResponse {
  member_id: string
  name: string
  role: string
}
