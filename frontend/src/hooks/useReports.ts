import { useQuery } from '@tanstack/react-query'
import { getReportDetail } from '../api/reports'

export function useReportDetail(id: string) {
  return useQuery({
    queryKey: ['reports', id],
    queryFn: () => getReportDetail(id),
    enabled: !!id,
  })
}
