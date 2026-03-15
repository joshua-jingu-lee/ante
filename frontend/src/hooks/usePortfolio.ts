import { useQuery } from '@tanstack/react-query'
import { getPortfolioValue, getPortfolioHistory } from '../api/portfolio'
import type { Period } from '../types/portfolio'

export function usePortfolioValue() {
  return useQuery({
    queryKey: ['portfolio', 'value'],
    queryFn: getPortfolioValue,
    staleTime: 30_000,
  })
}

export function usePortfolioHistory(period: Period) {
  return useQuery({
    queryKey: ['portfolio', 'history', period],
    queryFn: () => getPortfolioHistory(period),
    staleTime: 60_000,
  })
}
