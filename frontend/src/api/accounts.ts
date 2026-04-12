import client from './client'
import type { Account } from '../types/account'

export async function getAccounts(params?: { status?: string }): Promise<Account[]> {
  const res = await client.get('/api/accounts', { params })
  return res.data.accounts ?? []
}
