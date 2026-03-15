import client from './client'
import type { Member, MemberDetail, MemberCreateRequest } from '../types/member'

export async function getMembers(params?: {
  type?: string
  org?: string
  status?: string
}): Promise<Member[]> {
  const res = await client.get('/api/members', { params })
  return res.data
}

export async function getMemberDetail(id: string): Promise<MemberDetail> {
  const res = await client.get(`/api/members/${id}`)
  return res.data
}

export async function createMember(data: MemberCreateRequest): Promise<{ token: string }> {
  const res = await client.post('/api/members', data)
  return res.data
}

export async function suspendMember(id: string): Promise<void> {
  await client.post(`/api/members/${id}/suspend`)
}

export async function reactivateMember(id: string): Promise<void> {
  await client.post(`/api/members/${id}/reactivate`)
}

export async function revokeMember(id: string): Promise<void> {
  await client.post(`/api/members/${id}/revoke`)
}

export async function rotateToken(id: string): Promise<{ token: string }> {
  const res = await client.post(`/api/members/${id}/rotate-token`)
  return res.data
}

export async function updateScopes(id: string, scopes: string[]): Promise<void> {
  await client.put(`/api/members/${id}/scopes`, { scopes })
}
