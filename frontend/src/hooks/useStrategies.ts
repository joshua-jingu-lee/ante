import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getStrategies, getStrategyDetail, getStrategyPerformance, getStrategyTrades, getStrategyDailySummary, getStrategyWeeklySummary, getStrategyMonthlySummary, getStrategyTradesPaginated, updateStrategyStatus } from '../api/strategies'
import { showToast } from '../components/common/Toast'

export function useStrategies(params?: { search?: string }) {
  return useQuery({
    queryKey: ['strategies', params],
    queryFn: () => getStrategies(params),
  })
}

export function useStrategyDetail(id: string) {
  return useQuery({
    queryKey: ['strategies', id],
    queryFn: () => getStrategyDetail(id),
    enabled: !!id,
  })
}

export function useStrategyPerformance(id: string) {
  return useQuery({
    queryKey: ['strategies', id, 'performance'],
    queryFn: () => getStrategyPerformance(id),
    enabled: !!id,
  })
}

export function useStrategyTrades(id: string, cursor?: number) {
  return useQuery({
    queryKey: ['strategies', id, 'trades', cursor],
    queryFn: () => getStrategyTrades(id, { cursor, limit: 100 }),
    enabled: !!id,
  })
}

export function useStrategyDailySummary(id: string) {
  return useQuery({
    queryKey: ['strategies', id, 'daily-summary'],
    queryFn: () => getStrategyDailySummary(id),
    enabled: !!id,
  })
}

export function useStrategyWeeklySummary(id: string) {
  return useQuery({
    queryKey: ['strategies', id, 'weekly-summary'],
    queryFn: () => getStrategyWeeklySummary(id),
    enabled: !!id,
  })
}

export function useStrategyMonthlySummary(id: string) {
  return useQuery({
    queryKey: ['strategies', id, 'monthly-summary'],
    queryFn: () => getStrategyMonthlySummary(id),
    enabled: !!id,
  })
}

export function useStrategyTradesPaginated(
  id: string,
  params?: { offset?: number; limit?: number; side?: string; start_date?: string; end_date?: string },
) {
  return useQuery({
    queryKey: ['strategies', id, 'trades-paginated', params],
    queryFn: () => getStrategyTradesPaginated(id, params),
    enabled: !!id,
  })
}

export function useStrategyStatusTransition() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateStrategyStatus(id, status),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['strategies', variables.id] })
      showToast('전략 상태가 변경되었습니다.', 'success')
    },
    onError: () => {
      showToast('전략 상태 변경에 실패했습니다.', 'error')
    },
  })
}
