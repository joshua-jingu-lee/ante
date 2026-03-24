import client from './client'
import type { Bot, BotDetail, BotCreateRequest, BotUpdateRequest, HandlePositions } from '../types/bot'

function mapBot(raw: Record<string, unknown>): Bot {
  const mapped: Record<string, unknown> = {
    ...raw,
    strategy_name: raw.strategy_name ?? raw.strategy_id,
    mode: raw.mode ?? raw.bot_type,
  }

  // config 블록이 없으면 flat 필드에서 조립
  if (!mapped.config && raw.auto_restart !== undefined) {
    mapped.config = {
      interval_seconds: raw.interval_seconds as number,
      auto_restart: raw.auto_restart as boolean,
      max_restart_attempts: raw.max_restart_attempts as number,
      restart_cooldown_seconds: raw.restart_cooldown_seconds as number,
      step_timeout_seconds: raw.step_timeout_seconds as number,
      max_signals_per_step: raw.max_signals_per_step as number,
    }
  }

  return mapped as unknown as Bot
}

export async function getBots(): Promise<{ items: Bot[] }> {
  const res = await client.get('/api/bots')
  const bots = (res.data.bots ?? []) as Record<string, unknown>[]
  return { items: bots.map(mapBot) }
}

export async function getBotDetail(botId: string): Promise<BotDetail> {
  const res = await client.get(`/api/bots/${botId}`)
  const raw = res.data.bot ?? res.data
  return mapBot(raw) as BotDetail
}

export async function createBot(data: BotCreateRequest): Promise<Bot> {
  const res = await client.post('/api/bots', data)
  return res.data
}

export async function startBot(botId: string): Promise<void> {
  await client.post(`/api/bots/${botId}/start`)
}

export async function stopBot(botId: string): Promise<void> {
  await client.post(`/api/bots/${botId}/stop`)
}

export async function updateBot(botId: string, data: BotUpdateRequest): Promise<BotDetail> {
  const res = await client.put(`/api/bots/${botId}`, data)
  const raw = res.data.bot ?? res.data
  return mapBot(raw) as BotDetail
}

export async function deleteBot(botId: string, handlePositions?: HandlePositions): Promise<void> {
  await client.delete(`/api/bots/${botId}`, {
    params: handlePositions ? { handle_positions: handlePositions } : undefined,
  })
}
