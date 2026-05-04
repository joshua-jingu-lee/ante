import client from './client'
import type { SystemStatusView, DynamicConfigView } from '../types/system'
import type {
  ClearHaltRequest,
  ConfigItem,
  ConfigListResponse,
  ConfigUpdateResponse,
  HaltRequest,
  KillSwitchResponse,
  StatusResponse,
} from '../types/api.generated'

function optionalString(value: string | null | undefined): string | undefined {
  return value ?? undefined
}

function toSystemStatusView(raw: StatusResponse): SystemStatusView {
  return {
    status: raw.status,
    version: raw.version,
    haltTime: optionalString(raw.halt_time),
    haltReason: optionalString(raw.halt_reason),
  }
}

function toDynamicConfigView(raw: ConfigItem): DynamicConfigView {
  return {
    key: raw.key,
    value: raw.value == null ? '' : String(raw.value),
    description: typeof raw.description === 'string' ? raw.description : undefined,
  }
}

export async function getSystemStatus(): Promise<SystemStatusView> {
  const res = await client.get<StatusResponse>('/api/system/status')
  return toSystemStatusView(res.data)
}

/**
 * 전역 거래 정지 (모든 ACTIVE 계좌 → SUSPENDED).
 *
 * SSOT: `docs/specs/web-api/04-system-endpoints.md` Kill Switch.
 * 백엔드: `POST /api/system/halt` (HaltRequest { reason: string }).
 */
export async function haltSystem(reason?: string): Promise<KillSwitchResponse> {
  const body: HaltRequest = { reason: reason ?? '' }
  const res = await client.post<KillSwitchResponse>('/api/system/halt', body)
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
  const body: ClearHaltRequest = { reason: reason ?? '' }
  const res = await client.post<KillSwitchResponse>('/api/system/clear-halt', body)
  return res.data
}

export async function getConfigs(): Promise<DynamicConfigView[]> {
  const res = await client.get<ConfigListResponse>('/api/config')
  return res.data.configs.map(toDynamicConfigView)
}

export async function updateConfig(key: string, value: string): Promise<void> {
  await client.put<ConfigUpdateResponse>(`/api/config/${encodeURIComponent(key)}`, { value })
}
