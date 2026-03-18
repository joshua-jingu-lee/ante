import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
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
      {/* 에이전트 정보 헤더 — 목업 detail-header 기준 */}
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-border">
        <div>
          <h2 className="text-[20px] font-bold font-mono mb-1">{member.member_id}</h2>
          <div className="flex gap-2 items-center">
            <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
              {MEMBER_STATUS_LABELS[member.status]}
            </StatusBadge>
            <StatusBadge variant="muted">{member.org}</StatusBadge>
            <span className="text-text-muted text-[13px]">{member.name}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {member.status === 'active' && (
            <button onClick={() => suspend.mutate(member.member_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">정지</button>
          )}
          {member.status === 'suspended' && (
            <button onClick={() => reactivate.mutate(member.member_id)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">재활성화</button>
          )}
          {member.status !== 'revoked' && (
            <button onClick={() => { if (confirm('영구 폐기하시겠습니까?')) revoke.mutate(member.member_id) }} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative-hover">폐기</button>
          )}
        </div>
      </div>

      {/* 기본 정보 + 활동 정보 — 목업 detail-grid 기준 (2열) */}
      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* 기본 정보 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">기본 정보</h3>
          <div className="space-y-0">
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">Agent ID</span>
              <span className="font-mono">{member.member_id}</span>
            </div>
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">이름</span>
              <span>{member.name}</span>
            </div>
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">소속</span>
              <span>{member.org}</span>
            </div>
            <div className="flex justify-between py-2.5 text-[13px]">
              <span className="text-text-muted">상태</span>
              <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
                {MEMBER_STATUS_LABELS[member.status]}
              </StatusBadge>
            </div>
          </div>
        </div>

        {/* 활동 정보 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">활동 정보</h3>
          <div className="space-y-0">
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">생성일</span>
              <span>{formatDateTime(member.created_at)}</span>
            </div>
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">생성자</span>
              <span>{member.created_by || '-'}</span>
            </div>
            <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
              <span className="text-text-muted">마지막 활동</span>
              <span>{member.last_active_at ? formatDateTime(member.last_active_at) : '-'}</span>
            </div>
            <div className="flex justify-between py-2.5 text-[13px]">
              <span className="text-text-muted">정지 시각</span>
              <span className={member.suspended_at ? '' : 'text-text-muted'}>{member.suspended_at ? formatDateTime(member.suspended_at) : '-'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 토큰 관리 — 목업 기준 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <div className="flex items-center justify-between">
          <h3 className="text-[15px] font-semibold">토큰 관리</h3>
        </div>
        <div className="flex items-center gap-4 mt-3">
          <div className="flex-1">
            {member.token_prefix && (
              <div className="flex justify-between py-2.5 border-b border-border text-[13px]">
                <span className="text-text-muted">토큰 접두어</span>
                <span className="font-mono">{member.token_prefix}****</span>
              </div>
            )}
          </div>
          <button
            onClick={handleRotateToken}
            disabled={member.status === 'revoked'}
            className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover disabled:opacity-40 shrink-0"
          >
            토큰 재발급
          </button>
        </div>
        <p className="text-[12px] text-warning mt-2">{'⚠'} 토큰 재발급 시 기존 토큰이 즉시 무효화됩니다.</p>
      </div>

      {/* 권한 범위 (Scopes) — 목업 기준 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[15px] font-semibold">권한 범위 (Scopes)</h3>
          {!editingScopes ? (
            <button onClick={startEditScopes} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">편집</button>
          ) : null}
        </div>

        {/* 현재 scope 표시 */}
        <div className="flex flex-wrap gap-1 mb-4">
          {member.scopes.map((s) => (
            <span key={s} className="text-[11px] px-1.5 py-[1px] rounded-sm bg-bg border border-border text-text-muted font-mono">{s}</span>
          ))}
        </div>

        {/* scope 편집 (토글) */}
        {editingScopes && (
          <div className="border-t border-border pt-4">
            <div className="grid grid-cols-2 gap-2 mb-4">
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
            <div className="flex gap-2">
              <button onClick={() => { updateScopes.mutate({ id: member.member_id, scopes: scopesDraft }); setEditingScopes(false) }} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">저장</button>
              <button onClick={() => setEditingScopes(false)} className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
            </div>
          </div>
        )}
      </div>

      {/* 토큰 표시 모달 */}
      {newToken && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px] text-center">
            <h3 className="text-[18px] font-bold mb-4 text-positive">{'✓'} 새 토큰 발급 완료</h3>

            <div className="my-5">
              <div className="text-[12px] font-semibold text-text-muted">발급된 토큰</div>
              <div className="bg-bg border border-border rounded-lg p-3.5 font-mono text-[13px] break-all text-left mt-2">{newToken}</div>
            </div>

            <div className="bg-warning-bg text-warning p-3 rounded-lg text-[13px] mb-5 text-left">
              {'⚠'} 이 토큰은 다시 표시되지 않습니다. 안전한 곳에 복사해 두세요.
            </div>

            <div className="flex justify-center gap-2">
              <button onClick={() => navigator.clipboard.writeText(newToken)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">토큰 복사</button>
              <button onClick={() => setNewToken(null)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">닫기</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
