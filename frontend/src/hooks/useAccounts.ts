import { useQuery } from '@tanstack/react-query'
import { getAccounts } from '../api/accounts'

export function useAccounts(
  params?: { status?: string },
  options?: { refetchInterval?: number },
) {
  return useQuery({
    queryKey: ['accounts', params],
    queryFn: () => getAccounts(params),
    refetchInterval: options?.refetchInterval,
  })
}

/** 활성 계좌만 조회하는 편의 훅. */
export function useActiveAccounts() {
  return useAccounts({ status: 'active' })
}
