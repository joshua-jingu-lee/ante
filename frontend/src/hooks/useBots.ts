import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getBots, getBotDetail, createBot, startBot, stopBot, deleteBot } from '../api/bots'
import type { BotCreateRequest } from '../types/bot'

export function useBots() {
  return useQuery({
    queryKey: ['bots'],
    queryFn: getBots,
  })
}

export function useBotDetail(botId: string) {
  return useQuery({
    queryKey: ['bots', botId],
    queryFn: () => getBotDetail(botId),
    enabled: !!botId,
  })
}

export function useCreateBot() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: BotCreateRequest) => createBot(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
  })
}

export function useBotControl() {
  const queryClient = useQueryClient()
  return {
    start: useMutation({
      mutationFn: startBot,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    }),
    stop: useMutation({
      mutationFn: stopBot,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    }),
    remove: useMutation({
      mutationFn: deleteBot,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    }),
  }
}
