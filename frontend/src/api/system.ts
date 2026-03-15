import client from './client'
import type { SystemStatus, DynamicConfig } from '../types/system'

export async function getSystemStatus(): Promise<SystemStatus> {
  const res = await client.get('/api/system/status')
  return res.data
}

export async function setKillSwitch(enabled: boolean): Promise<void> {
  await client.post('/api/system/kill-switch', { enabled })
}

export async function getConfigs(): Promise<DynamicConfig[]> {
  const res = await client.get('/api/config')
  return res.data
}

export async function updateConfig(key: string, value: string): Promise<void> {
  await client.put(`/api/config/${encodeURIComponent(key)}`, { value })
}
