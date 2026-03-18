import { useState } from 'react'
import { useUpdateApprovalStatus } from '../../hooks/useApprovals'
import Modal from '../common/Modal'
import StatusBadge from '../common/StatusBadge'
import type { ApprovalReview, ApprovalType } from '../../types/approval'

const APPROVE_ACTION_TEXT: Record<ApprovalType, string> = {
  strategy_adopt: '전략이 채택 상태로 전환됩니다.',
  strategy_report: '전략 리포트가 채택됩니다.',
  budget_change: 'Treasury에서 예산이 즉시 재배분됩니다.',
  budget_allocate: 'Treasury에서 예산이 할당됩니다.',
  bot_create: 'BotManager에서 봇이 즉시 생성됩니다.',
  bot_stop: '해당 봇의 거래가 즉시 중지됩니다.',
  live_switch: '봇이 모의투자에서 실전투자로 전환됩니다.',
  risk_alert: '위험 알림이 처리 완료됩니다.',
  rule_change: 'RuleEngine에서 해당 봇의 규칙이 즉시 갱신됩니다.',
}

interface ReviewControlsProps {
  approvalId: string
  isPending: boolean
  title: string
  reviews?: ApprovalReview[]
  type?: ApprovalType
  params?: Record<string, unknown>
}

function formatCurrency(value: unknown): string {
  const num = Number(value)
  if (isNaN(num)) return String(value ?? '-')
  return `${num.toLocaleString()}원`
}

function ApproveModalSummary({ type, params }: { type?: ApprovalType; params?: Record<string, unknown> }) {
  if (!type || !params) return null

  if (type === 'bot_create') {
    const tradeMode = String(params.trade_mode ?? '')
    const isMock = tradeMode === 'mock' || tradeMode === '모의투자'
    return (
      <div className="text-[13px] text-text-muted mb-4">
        전략: <span className="font-mono">{String(params.strategy_name ?? '-')}</span>
        {' · '}예산: {formatCurrency(params.budget)}
        {' · '}모드: {isMock
          ? <StatusBadge variant="warning">모의투자</StatusBadge>
          : <StatusBadge variant="positive">실전투자</StatusBadge>}
      </div>
    )
  }

  if (type === 'budget_change') {
    const current = Number(params.current_budget ?? 0)
    const requested = Number(params.requested_budget ?? 0)
    const diff = requested - current
    return (
      <div className="text-[13px] text-text-muted mb-4">
        예산: {formatCurrency(current)} → <strong className="text-positive">{formatCurrency(requested)}</strong> ({diff >= 0 ? '+' : ''}{formatCurrency(diff)})
      </div>
    )
  }

  return null
}

export default function ReviewControls({ approvalId, isPending, title, reviews, type, params }: ReviewControlsProps) {
  const [showApprove, setShowApprove] = useState(false)
  const [showReject, setShowReject] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const updateStatus = useUpdateApprovalStatus()

  if (!isPending) return null

  const hasWarnings = reviews?.some((r) => r.result === 'warn' || r.result === 'fail') ?? false

  const handleApprove = () => {
    updateStatus.mutate({ id: approvalId, status: 'approved' }, {
      onSuccess: () => setShowApprove(false),
    })
  }

  const handleReject = () => {
    if (!rejectReason.trim()) return
    updateStatus.mutate({ id: approvalId, status: 'rejected', memo: rejectReason.trim() }, {
      onSuccess: () => { setShowReject(false); setRejectReason('') },
    })
  }

  return (
    <>
      <div className="flex gap-2">
        <button
          onClick={() => setShowReject(true)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text border border-border cursor-pointer hover:bg-surface-hover"
        >
          거부
        </button>
        <button
          onClick={() => setShowApprove(true)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover"
        >
          승인
        </button>
      </div>

      {/* 승인 확인 모달 */}
      <Modal open={showApprove} onClose={() => setShowApprove(false)}>
        <div className="text-[16px] font-semibold text-positive mb-4">결재 승인</div>
        <div className="text-[13px] text-text-muted mb-4">
          <strong className="text-text">{title}</strong>을 승인하시겠습니까?
        </div>
        <ApproveModalSummary type={type} params={params} />
        {type && (
          <div className="bg-info/10 text-info p-3 rounded text-[12px] mb-4">
            {'\uD83D\uDCA1'} 승인 시 <strong>{APPROVE_ACTION_TEXT[type]}</strong>
          </div>
        )}
        {hasWarnings && (
          <div className="bg-warning/10 text-warning p-3 rounded text-[12px] mb-4">
            {'\u26A0'} 검토 의견에 <strong>warn</strong> 또는 <strong>fail</strong> 결과가 포함되어 있습니다. 검증 내용을 확인하세요.
          </div>
        )}
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={() => setShowApprove(false)}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text border border-border cursor-pointer hover:bg-surface-hover"
          >
            취소
          </button>
          <button
            onClick={handleApprove}
            disabled={updateStatus.isPending}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover disabled:opacity-50"
          >
            승인
          </button>
        </div>
      </Modal>

      {/* 거부 확인 모달 */}
      <Modal open={showReject} onClose={() => setShowReject(false)}>
        <div className="text-[16px] font-semibold text-negative mb-4">결재 거부</div>
        <div className="text-[13px] text-text-muted mb-4">
          <strong className="text-text">{title}</strong>을 거부하시겠습니까?
        </div>
        <div className="mb-4">
          <label className="block text-[12px] font-semibold text-text-muted mb-1.5">거부 사유</label>
          <input
            type="text"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="예: 변동성 구간 추가 검증 필요"
            aria-label="거부 사유"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-text text-[13px] focus:outline-none focus:border-primary"
          />
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={() => setShowReject(false)}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text border border-border cursor-pointer hover:bg-surface-hover"
          >
            취소
          </button>
          <button
            onClick={handleReject}
            disabled={updateStatus.isPending || !rejectReason.trim()}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative-hover disabled:opacity-50"
          >
            거부
          </button>
        </div>
      </Modal>
    </>
  )
}
