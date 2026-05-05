import client from './client'
import type {
  BotBudgetDetail,
  BotConfig,
  BotCreateInput,
  BotDetailView,
  BotLog,
  BotLogResult,
  BotPosition,
  BotStatus,
  BotStrategy,
  BotTradingMode,
  BotUpdateInput,
  BotView,
  HandlePositions,
} from '../types/bot'
import type {
  BotCreateRequest,
  BotDetailResponse,
  BotInfo,
  BotListResponse,
  BotUpdateRequest,
} from '../types/api.generated'

type BotInfoWithExtra = BotInfo & Record<string, unknown>

const BOT_STATUSES = new Set<BotStatus>([
  'created',
  'running',
  'stopping',
  'stopped',
  'error',
  'deleted',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' ? value : fallback
}

function booleanValue(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function toBotStatus(value: string): BotStatus {
  return BOT_STATUSES.has(value as BotStatus) ? (value as BotStatus) : 'error'
}

function toTradingMode(value: unknown): BotTradingMode {
  return typeof value === 'string' && value.toLowerCase() === 'live' ? 'live' : 'virtual'
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function toBotConfig(raw: BotInfoWithExtra): BotConfig | undefined {
  if (isRecord(raw.config)) {
    return {
      interval_seconds: numberValue(raw.config.interval_seconds, raw.interval_seconds),
      auto_restart: booleanValue(raw.config.auto_restart),
      max_restart_attempts: numberValue(raw.config.max_restart_attempts),
      restart_cooldown_seconds: numberValue(raw.config.restart_cooldown_seconds),
      step_timeout_seconds: numberValue(raw.config.step_timeout_seconds),
      max_signals_per_step: numberValue(raw.config.max_signals_per_step),
    }
  }

  if (raw.auto_restart === undefined) return undefined

  return {
    interval_seconds: numberValue(raw.interval_seconds, raw.interval_seconds),
    auto_restart: booleanValue(raw.auto_restart),
    max_restart_attempts: numberValue(raw.max_restart_attempts),
    restart_cooldown_seconds: numberValue(raw.restart_cooldown_seconds),
    step_timeout_seconds: numberValue(raw.step_timeout_seconds),
    max_signals_per_step: numberValue(raw.max_signals_per_step),
  }
}

function toBotStrategy(value: unknown): BotStrategy | undefined {
  if (!isRecord(value)) return undefined
  return {
    name: stringValue(value.name),
    version: stringValue(value.version),
    author_name: stringValue(value.author_name),
    author_id: stringValue(value.author_id),
    description: stringValue(value.description),
  }
}

function toBotBudgetDetail(value: unknown): BotBudgetDetail | undefined {
  if (!isRecord(value)) return undefined
  return {
    allocated: numberValue(value.allocated),
    spent: numberValue(value.spent),
    reserved: numberValue(value.reserved),
    available: numberValue(value.available),
  }
}

function toBotPosition(value: unknown): BotPosition | undefined {
  if (!isRecord(value) || typeof value.symbol !== 'string') return undefined
  return {
    symbol: value.symbol,
    quantity: numberValue(value.quantity),
    avg_entry_price: numberValue(value.avg_entry_price),
    current_price: typeof value.current_price === 'number' ? value.current_price : undefined,
    realized_pnl: numberValue(value.realized_pnl),
  }
}

function toBotLogResult(value: unknown): BotLogResult | undefined {
  return value === 'success' || value === 'failure' || value === 'stopped' ? value : undefined
}

function toBotLog(value: unknown): BotLog | undefined {
  if (!isRecord(value)) return undefined
  return {
    timestamp: stringValue(value.timestamp),
    success: booleanValue(value.success),
    result: toBotLogResult(value.result),
    message: optionalString(value.message),
  }
}

function toBotView(raw: BotInfo): BotView {
  const extra = raw as BotInfoWithExtra
  return {
    bot_id: raw.bot_id,
    name: raw.name,
    strategy_name: raw.strategy_name ?? raw.strategy_id,
    status: toBotStatus(raw.status),
    trading_mode: toTradingMode(extra.trading_mode),
    interval_seconds: raw.interval_seconds,
    created_at: stringValue(extra.created_at),
  }
}

function toBotDetailView(raw: BotInfo): BotDetailView {
  const extra = raw as BotInfoWithExtra
  const positions = Array.isArray(extra.positions)
    ? extra.positions.map(toBotPosition).filter((pos): pos is BotPosition => pos !== undefined)
    : undefined
  const logs = Array.isArray(extra.logs)
    ? extra.logs.map(toBotLog).filter((log): log is BotLog => log !== undefined)
    : []

  return {
    ...toBotView(raw),
    interval_seconds: raw.interval_seconds,
    symbols: toStringArray(extra.symbols),
    allocated_budget: numberValue(extra.allocated_budget),
    logs,
    strategy: toBotStrategy(extra.strategy),
    strategy_author_name: raw.strategy_author_name ?? undefined,
    strategy_author_id: raw.strategy_author_id ?? undefined,
    config: toBotConfig(extra),
    budget: toBotBudgetDetail(extra.budget),
    positions,
  }
}

function toBotCreateRequest(data: BotCreateInput): BotCreateRequest {
  return {
    bot_id: data.bot_id,
    name: data.name ?? '',
    strategy_id: data.strategy_id ?? null,
    strategy_name: data.strategy_name ?? null,
    account_id: data.account_id ?? null,
    interval_seconds: data.interval_seconds ?? 60,
    budget: data.budget ?? null,
  }
}

function toBotUpdateRequest(data: BotUpdateInput): BotUpdateRequest {
  return {
    name: data.name ?? null,
    strategy_name: data.strategy_name ?? null,
    interval_seconds: data.interval_seconds ?? null,
    budget: data.budget ?? null,
    auto_restart: data.auto_restart ?? null,
    max_restart_attempts: data.max_restart_attempts ?? null,
    restart_cooldown_seconds: data.restart_cooldown_seconds ?? null,
    step_timeout_seconds: data.step_timeout_seconds ?? null,
    max_signals_per_step: data.max_signals_per_step ?? null,
  }
}

export async function getBots(): Promise<{ items: BotView[] }> {
  const res = await client.get<BotListResponse>('/api/bots')
  return { items: res.data.bots.map(toBotView) }
}

export async function getBotDetail(botId: string): Promise<BotDetailView> {
  const res = await client.get<BotDetailResponse>(`/api/bots/${botId}`)
  return toBotDetailView(res.data.bot)
}

export async function createBot(data: BotCreateInput): Promise<BotView> {
  const res = await client.post<BotDetailResponse>('/api/bots', toBotCreateRequest(data))
  return toBotDetailView(res.data.bot)
}

export async function startBot(botId: string): Promise<void> {
  await client.post<BotDetailResponse>(`/api/bots/${botId}/start`)
}

export async function stopBot(botId: string): Promise<void> {
  await client.post<BotDetailResponse>(`/api/bots/${botId}/stop`)
}

export async function updateBot(botId: string, data: BotUpdateInput): Promise<BotDetailView> {
  const res = await client.put<BotDetailResponse>(`/api/bots/${botId}`, toBotUpdateRequest(data))
  return toBotDetailView(res.data.bot)
}

export async function deleteBot(botId: string, handlePositions?: HandlePositions): Promise<void> {
  await client.delete<void>(`/api/bots/${botId}`, {
    params: handlePositions ? { handle_positions: handlePositions } : undefined,
  })
}
