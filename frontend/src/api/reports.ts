import client from './client'
import type { ReportDetail } from '../types/report'

export async function getReportDetail(id: string): Promise<ReportDetail> {
  const res = await client.get(`/api/reports/${id}`)
  return res.data
}
