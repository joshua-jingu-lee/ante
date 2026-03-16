import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSystemStatus, setKillSwitch, getConfigs, updateConfig } from '../api/system'

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system', 'status'],
    queryFn: getSystemStatus,
    refetchInterval: 30_000,
  })
}

export function useKillSwitch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ action, reason }: { action: 'halt' | 'activate'; reason?: string }) =>
      setKillSwitch(action, reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['system'] }),
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
