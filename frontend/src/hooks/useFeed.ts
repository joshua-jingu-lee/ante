import { useQuery } from '@tanstack/react-query'
import { getFeedStatus } from '../api/data'

export function useFeedStatus() {
  return useQuery({
    queryKey: ['data', 'feed-status'],
    queryFn: getFeedStatus,
    refetchInterval: 60_000,
  })
}
