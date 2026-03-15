/** API 기본 URL */
export const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/** 봇 상태 라벨 */
export const BOT_STATUS_LABELS: Record<string, string> = {
  created: '생성됨',
  running: '실행 중',
  stopping: '중지 중',
  stopped: '중지됨',
  error: '오류',
  deleted: '삭제됨',
}

/** 전략 상태 라벨 */
export const STRATEGY_STATUS_LABELS: Record<string, string> = {
  registered: '등록됨',
  active: '활성',
  inactive: '비활성',
  archived: '보관됨',
}

/** 결재 상태 라벨 */
export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: '대기',
  approved: '승인',
  rejected: '거부',
}

/** 멤버 상태 라벨 */
export const MEMBER_STATUS_LABELS: Record<string, string> = {
  active: '활성',
  suspended: '정지',
  revoked: '폐기',
}
