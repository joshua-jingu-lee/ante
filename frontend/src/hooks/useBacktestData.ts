import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDatasets, getDatasetDetail, getStorageInfo, deleteDataset } from '../api/data'
import type { Dataset } from '../types/data'

export function useDatasets(params?: {
  symbol?: string
  timeframe?: string
  data_type?: 'ohlcv' | 'fundamental'
  offset?: number
  limit?: number
}) {
  return useQuery({
    queryKey: ['datasets-all', params],
    queryFn: () => getDatasets(params),
  })
}

export function useDatasetDetail(datasetId: string | null) {
  return useQuery({
    queryKey: ['dataset-detail', datasetId],
    queryFn: () => getDatasetDetail(datasetId!),
    enabled: !!datasetId,
  })
}

export function useStorageInfo() {
  return useQuery({
    queryKey: ['storage'],
    queryFn: getStorageInfo,
  })
}

export function useDeleteDataset() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (target: Dataset) => deleteDataset(target.id, target.data_type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['datasets-all'] })
      queryClient.invalidateQueries({ queryKey: ['storage'] })
    },
  })
}
