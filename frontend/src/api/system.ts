import client from './client'
import type { SystemStatus, DynamicConfig } from '../types/system'
import type { KillSwitchResponse } from '../types/api.generated'

export async function getSystemStatus(): Promise<SystemStatus> {
  const res = await client.get('/api/system/status')
  return res.data
}

/**
 * 전역 거래 정지 (모든 ACTIVE 계좌 → SUSPENDED).
 *
 * SSOT: `docs/specs/web-api/04-system-endpoints.md` Kill Switch.
 * 백엔드: `POST /api/system/halt` (HaltRequest { reason: string }).
 */
export async function haltSystem(reason?: string): Promise<KillSwitchResponse> {
  const res = await client.post('/api/system/halt', { reason: reason ?? '' })
  return res.data
}

/**
 * 전역 정지 해제 (모든 SUSPENDED 계좌 → ACTIVE).
 *
 * 계좌 상태만 ACTIVE로 복구하며 봇은 자동 재시작되지 않는다.
 * SSOT: `docs/specs/web-api/04-system-endpoints.md` Kill Switch.
 * 백엔드: `POST /api/system/clear-halt` (ClearHaltRequest { reason: string }).
 */
export async function clearHaltSystem(reason?: string): Promise<KillSwitchResponse> {
  const res = await client.post('/api/system/clear-halt', { reason: reason ?? '' })
  return res.data
}

export async function getConfigs(): Promise<DynamicConfig[]> {
  const res = await client.get('/api/config')
  return res.data.configs ?? res.data
}

export async function updateConfig(key: string, value: string): Promise<void> {
  await client.put(`/api/config/${encodeURIComponent(key)}`, { value })
}
