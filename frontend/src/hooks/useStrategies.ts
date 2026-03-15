import { useQuery } from '@tanstack/react-query'
import { getStrategies, getStrategyDetail, getStrategyPerformance, getStrategyTrades } from '../api/strategies'

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: getStrategies,
  })
}

export function useStrategyDetail(id: number) {
  return useQuery({
    queryKey: ['strategies', id],
    queryFn: () => getStrategyDetail(id),
    enabled: id > 0,
  })
}

export function useStrategyPerformance(id: number) {
  return useQuery({
    queryKey: ['strategies', id, 'performance'],
    queryFn: () => getStrategyPerformance(id),
    enabled: id > 0,
  })
}

export function useStrategyTrades(id: number, cursor?: number) {
  return useQuery({
    queryKey: ['strategies', id, 'trades', cursor],
    queryFn: () => getStrategyTrades(id, { cursor, limit: 100 }),
    enabled: id > 0,
  })
}
