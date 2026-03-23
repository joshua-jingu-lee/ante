import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getTreasurySummary, getBotBudgets, allocateBudget, deallocateBudget, getTreasuryTransactions, getTreasurySnapshots } from '../api/treasury'

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

export function useTreasurySnapshots(params: {
  account_id?: string
  start_date?: string
  end_date?: string
}) {
  return useQuery({
    queryKey: ['treasury', 'snapshots', params],
    queryFn: () => getTreasurySnapshots(params),
  })
}

export function useTreasuryTransactions(params: {
  offset?: number
  limit?: number
  type?: string
  bot_id?: string
}) {
  return useQuery({
    queryKey: ['treasury', 'transactions', params],
    queryFn: () => getTreasuryTransactions(params),
  })
}
