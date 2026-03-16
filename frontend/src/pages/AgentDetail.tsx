import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMemberDetail, useMemberControl } from '../hooks/useMembers'
import StatusBadge from '../components/common/StatusBadge'
import { PageSkeleton } from '../components/common/Skeleton'
import { formatDateTime } from '../utils/formatters'
import { MEMBER_STATUS_LABELS } from '../utils/constants'
import { ALL_SCOPES, type MemberStatus } from '../types/member'

const STATUS_VARIANT: Record<MemberStatus, string> = {
  active: 'positive', suspended: 'warning', revoked: 'negative',
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: member, isLoading } = useMemberDetail(id!)
  const { suspend, reactivate, revoke, rotateToken, updateScopes } = useMemberControl()
  const [newToken, setNewToken] = useState<string | null>(null)
  const [editingScopes, setEditingScopes] = useState(false)
  const [scopesDraft, setScopesDraft] = useState<string[]>([])

  if (isLoading) return <PageSkeleton />
  if (!member) return <div className="text-text-muted text-center py-12">에이전트를 찾을 수 없습니다</div>

  const startEditScopes = () => {
    setScopesDraft([...member.scopes])
    setEditingScopes(true)
  }

  const handleRotateToken = () => {
    if (!confirm('기존 토큰이 즉시 무효화됩니다. 계속하시겠습니까?')) return
    rotateToken.mutateAsync(member.member_id).then((data) => setNewToken(data.token))
  }

  return (
    <>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="w-[56px] h-[56px] rounded-full bg-surface border border-border flex items-center justify-center text-[28px] shrink-0">
            {member.emoji || (member.type === 'human' ? '👤' : '🤖')}
          </div>
          <div>
            <h2 className="text-[20px] font-bold font-mono">{member.member_id}</h2>
            <div className="flex gap-3 items-center mt-1">
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded">{member.org}</span>
              <span className="text-text-muted text-[13px]">{member.name}</span>
              <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
                {MEMBER_STATUS_LABELS[member.status]}
              </StatusBadge>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {member.status === 'active' && (
            <button onClick={() => suspend.mutate(member.member_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-warning border border-border cursor-pointer hover:bg-warning-bg">정지</button>
          )}
          {member.status === 'suspended' && (
            <button onClick={() => reactivate.mutate(member.member_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">재활성화</button>
          )}
          {member.status !== 'revoked' && (
            <button onClick={() => { if (confirm('영구 폐기하시겠습니까?')) revoke.mutate(member.member_id) }} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-negative border border-border cursor-pointer hover:bg-negative-bg">폐기</button>
          )}
        </div>
      </div>

      {/* 기본 정보 카드 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-3">기본 정보</h3>
        <div className="grid grid-cols-2 gap-x-8 gap-y-2">
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">Agent ID</span>
            <span className="font-mono">{member.member_id}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">이름</span>
            <span>{member.name}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">소속</span>
            <span>{member.org}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">상태</span>
            <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
              {MEMBER_STATUS_LABELS[member.status]}
            </StatusBadge>
          </div>
        </div>
      </div>

      {/* 토큰 관리 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">토큰 관리</h3>
          <button
            onClick={handleRotateToken}
            disabled={member.status === 'revoked'}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover disabled:opacity-40"
          >
            토큰 재발급
          </button>
        </div>
        {member.token_prefix && (
          <div className="flex justify-between py-2 border-b border-border text-[13px] mb-3">
            <span className="text-text-muted">토큰 접두어</span>
            <span className="font-mono">{member.token_prefix}****</span>
          </div>
        )}
        <p className="text-[12px] text-warning">기존 토큰이 즉시 무효화됩니다</p>
      </div>

      {/* 권한 범위 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[15px] font-semibold">권한 범위</h3>
          {!editingScopes ? (
            <button onClick={startEditScopes} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">편집</button>
          ) : (
            <div className="flex gap-2">
              <button onClick={() => { updateScopes.mutate({ id: member.member_id, scopes: scopesDraft }); setEditingScopes(false) }} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">저장</button>
              <button onClick={() => setEditingScopes(false)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
            </div>
          )}
        </div>
        {editingScopes ? (
          <div className="grid grid-cols-2 gap-2">
            {ALL_SCOPES.map((scope) => (
              <label key={scope} className="flex items-center gap-2 text-[13px] cursor-pointer">
                <input
                  type="checkbox"
                  checked={scopesDraft.includes(scope)}
                  onChange={() => setScopesDraft((prev) => prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope])}
                  className="accent-primary"
                />
                <span className="font-mono text-[12px]">{scope}</span>
              </label>
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {member.scopes.map((s) => (
              <span key={s} className="px-2 py-0.5 bg-positive-bg text-primary rounded text-[11px] font-medium font-mono">{s}</span>
            ))}
          </div>
        )}
      </div>

      {/* 활동 정보 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-3">활동 정보</h3>
        <div className="space-y-2">
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">생성일</span>
            <span>{formatDateTime(member.created_at)}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-border text-[13px]">
            <span className="text-text-muted">생성자</span>
            <span>{member.created_by || '-'}</span>
          </div>
          {member.suspended_at && (
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">정지 시각</span>
              <span>{formatDateTime(member.suspended_at)}</span>
            </div>
          )}
          <div className="flex justify-between py-2 text-[13px]">
            <span className="text-text-muted">마지막 활동</span>
            <span>{member.last_active_at ? formatDateTime(member.last_active_at) : '-'}</span>
          </div>
        </div>
      </div>

      {/* 토큰 표시 모달 */}
      {newToken && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold mb-4">새 토큰 발급 완료</h3>
            <p className="text-[13px] text-warning mb-3">이 토큰은 다시 확인할 수 없습니다.</p>
            <div className="bg-bg border border-border rounded-lg p-3 font-mono text-[12px] break-all mb-4">{newToken}</div>
            <div className="flex justify-end gap-2">
              <button onClick={() => navigator.clipboard.writeText(newToken)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">복사</button>
              <button onClick={() => setNewToken(null)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">닫기</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
