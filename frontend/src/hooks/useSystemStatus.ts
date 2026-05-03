import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getSystemStatus,
  haltSystem,
  clearHaltSystem,
  getConfigs,
  updateConfig,
} from '../api/system'

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system', 'status'],
    queryFn: getSystemStatus,
    refetchInterval: 30_000,
  })
}

/**
 * 전역 거래 정지 mutation.
 *
 * 성공 시 ['accounts'] + ['system'] 쿼리를 무효화하여 useAccounts 기반
 * Settings/Header 상태 표시가 즉시 SUSPENDED로 갱신되도록 한다.
 */
export function useHaltSystem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reason }: { reason?: string } = {}) => haltSystem(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      queryClient.invalidateQueries({ queryKey: ['system'] })
    },
  })
}

/**
 * 전역 정지 해제 mutation.
 *
 * 계좌 상태만 ACTIVE로 복구한다. 봇은 자동 재시작되지 않는다.
 * 성공 시 ['accounts'] + ['system'] 쿼리를 무효화한다.
 */
export function useClearHaltSystem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ reason }: { reason?: string } = {}) => clearHaltSystem(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      queryClient.invalidateQueries({ queryKey: ['system'] })
    },
  })
}

export function useConfigs() {
  return useQuery({
    queryKey: ['config'],
    queryFn: getConfigs,
  })
}

export function useUpdateConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => updateConfig(key, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config'] }),
  })
}
