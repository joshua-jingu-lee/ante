import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getTreasurySummary, getBotBudgets, allocateBudget, deallocateBudget, getTreasuryHistory } from '../api/treasury'

export function useTreasurySummary() {
  return useQuery({
    queryKey: ['treasury', 'summary'],
    queryFn: getTreasurySummary,
  })
}

export function useBotBudgets() {
  return useQuery({
    queryKey: ['treasury', 'budgets'],
    queryFn: getBotBudgets,
  })
}

export function useAllocateBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ botId, amount }: { botId: string; amount: number }) => allocateBudget(botId, amount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['treasury'] })
    },
  })
}

export function useDeallocateBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ botId, amount }: { botId: string; amount: number }) => deallocateBudget(botId, amount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['treasury'] })
    },
  })
}

export function useTreasuryHistory(offset = 0, limit = 20) {
  return useQuery({
    queryKey: ['treasury', 'history', offset, limit],
    queryFn: () => getTreasuryHistory({ offset, limit }),
  })
}
