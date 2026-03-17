import { useQuery } from '@tanstack/react-query'
import { getStrategies, getStrategyDetail, getStrategyPerformance, getStrategyTrades, getStrategyDailySummary, getStrategyMonthlySummary } from '../api/strategies'

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: getStrategies,
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

export function useStrategyMonthlySummary(id: string) {
  return useQuery({
    queryKey: ['strategies', id, 'monthly-summary'],
    queryFn: () => getStrategyMonthlySummary(id),
    enabled: !!id,
  })
}
