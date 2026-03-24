import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getBots, getBotDetail, createBot, updateBot, startBot, stopBot, deleteBot } from '../api/bots'
import type { BotCreateRequest, BotUpdateRequest, HandlePositions } from '../types/bot'

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

export function useBotUpdate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ botId, data }: { botId: string; data: BotUpdateRequest }) => updateBot(botId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['bots', variables.botId] })
      queryClient.invalidateQueries({ queryKey: ['bots'] })
    },
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
      mutationFn: ({ botId, handlePositions }: { botId: string; handlePositions?: HandlePositions }) =>
        deleteBot(botId, handlePositions),
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    }),
  }
}
