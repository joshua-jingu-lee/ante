import client from './client'
import type { LoginRequest, LoginResponse, User } from '../types/auth'

export async function login(data: LoginRequest): Promise<LoginResponse> {
  const res = await client.post('/api/auth/login', data)
  return res.data
}

export async function logout(): Promise<void> {
  await client.post('/api/auth/logout')
}

export async function getMe(): Promise<User> {
  const res = await client.get('/api/auth/me')
  return res.data
}
