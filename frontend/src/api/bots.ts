import client from './client'
import type { Bot, BotDetail, BotCreateRequest } from '../types/bot'

function mapBot(raw: Record<string, unknown>): Bot {
  return {
    ...raw,
    strategy_name: raw.strategy_name ?? raw.strategy_id,
    mode: raw.mode ?? raw.bot_type,
  } as Bot
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

export async function deleteBot(botId: string): Promise<void> {
  await client.delete(`/api/bots/${botId}`)
}
