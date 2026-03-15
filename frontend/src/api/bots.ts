import client from './client'
import type { Bot, BotDetail, BotCreateRequest } from '../types/bot'

export async function getBots(): Promise<{ items: Bot[] }> {
  const res = await client.get('/api/bots')
  return res.data
}

export async function getBotDetail(botId: string): Promise<BotDetail> {
  const res = await client.get(`/api/bots/${botId}`)
  return res.data
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
