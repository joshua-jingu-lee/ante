import type { ApprovalTypeRef } from '../types/approval'

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
  registered: '대기',
  adopted: '채택',
  active: '운용중',
  inactive: '중지',
  archived: '보관',
}

/** 결재 상태 라벨 */
export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: '대기',
  approved: '승인',
  rejected: '거부',
}

/**
 * 결재 유형 라벨. backend ``ApprovalType`` enum SSOT 와 정확히 일치한다
 * (#1471 — split #1418/C). SSOT: ``src/ante/approval/models.py:ApprovalType``.
 */
export const APPROVAL_TYPE_LABELS = {
  strategy_adopt: '전략 채택',
  strategy_retire: '전략 은퇴',
  bot_create: '봇 생성',
  bot_assign_strategy: '봇 전략 배정',
  bot_change_strategy: '봇 전략 변경',
  bot_stop: '봇 중지',
  bot_resume: '봇 재개',
  bot_delete: '봇 삭제',
  budget_change: '예산 변경',
  rule_change: '규칙 변경',
} as const

/**
 * 결재 승인 시 발생하는 부작용 설명 (승인 확인 모달).
 *
 * backend SSOT 와 정합한다 (#1471). 알려진 SSOT 유형이 아닌 경우
 * (``ApprovalTypeRef.kind === 'unknown'``) approve action 자체가 backend 에서
 * 거부되므로 (#1470) 별도 fallback 메시지를 두지 않는다.
 */
/**
 * ``ApprovalTypeRef`` 를 화면에 표시할 라벨로 변환한다 (#1471).
 *
 * - ``kind === 'known'``: 한국어 라벨.
 * - ``kind === 'unknown'``: ``unknown:{raw}`` 로 명시 표기 — operator 가 legacy
 *   invalid row / contract drift 를 즉시 인지할 수 있게 한다. silent fallback
 *   금지.
 */
export function approvalTypeLabel(ref: ApprovalTypeRef): string {
  if (ref.kind === 'known') return APPROVAL_TYPE_LABELS[ref.value]
  return `unknown:${ref.raw}`
}

/**
 * ``ApprovalTypeRef`` 의 ``StatusBadge`` variant.
 *
 * - 알려진 유형: ``muted`` (중립 표시).
 * - 알려지지 않은 유형: ``negative`` (operator 가 즉시 식별).
 */
export function approvalTypeVariant(ref: ApprovalTypeRef): 'muted' | 'negative' {
  return ref.kind === 'known' ? 'muted' : 'negative'
}

export const APPROVE_ACTION_TEXT = {
  strategy_adopt: '전략이 채택 상태로 전환됩니다.',
  strategy_retire: '전략이 은퇴 상태로 전환됩니다.',
  bot_create: 'BotManager 에서 봇이 즉시 생성됩니다.',
  bot_assign_strategy: '봇에 전략이 즉시 배정됩니다.',
  bot_change_strategy: '봇의 전략이 즉시 변경됩니다.',
  bot_stop: '해당 봇의 거래가 즉시 중지됩니다.',
  bot_resume: '해당 봇의 거래가 즉시 재개됩니다.',
  bot_delete: '해당 봇이 즉시 삭제됩니다.',
  budget_change: 'Treasury 에서 예산이 즉시 재배분됩니다.',
  rule_change: 'RuleEngine 에서 해당 봇의 규칙이 즉시 갱신됩니다.',
} as const

/** 멤버 상태 라벨 */
export const MEMBER_STATUS_LABELS: Record<string, string> = {
  active: '활성',
  suspended: '정지',
  revoked: '폐기',
}

/** 자금 변동 유형 라벨 (#1476: 5-value vocabulary와 일관) */
export const TRANSACTION_TYPE_LABELS: Record<string, string> = {
  allocate: '할당',
  deallocate: '회수',
  release: '회수(봇 삭제)',
  fill: '체결',
  bot_stopped_release: '예약해제',
}

/** 자금 변동 유형 뱃지 색상 */
export const TRANSACTION_TYPE_VARIANT: Record<string, string> = {
  allocate: 'positive',
  deallocate: 'warning',
  release: 'warning',
  fill: 'primary',
  bot_stopped_release: 'default',
}
