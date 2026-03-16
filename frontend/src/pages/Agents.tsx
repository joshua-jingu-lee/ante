import { useState } from 'react'
import { useMembers, useMemberControl } from '../hooks/useMembers'
import AgentTable from '../components/agents/AgentTable'
import AgentRegisterForm from '../components/agents/AgentRegisterForm'
import { TableSkeleton } from '../components/common/Skeleton'
import type { MemberStatus } from '../types/member'

const STATUS_FILTERS: { key: MemberStatus | 'all'; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'active', label: 'active' },
  { key: 'suspended', label: 'suspended' },
  { key: 'revoked', label: 'revoked' },
]

export default function Agents() {
  const [statusFilter, setStatusFilter] = useState<MemberStatus | 'all'>('all')
  const [showRegister, setShowRegister] = useState(false)
  const [createdToken, setCreatedToken] = useState<string | null>(null)

  const { data: members, isLoading } = useMembers({
    type: 'agent',
    status: statusFilter === 'all' ? undefined : statusFilter,
  })
  const { suspend, reactivate, revoke } = useMemberControl()

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1 bg-bg rounded-lg p-0.5">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className={`px-3.5 py-1.5 rounded text-[12px] font-medium border-none cursor-pointer ${
                statusFilter === f.key ? 'bg-surface text-text' : 'bg-transparent text-text-muted hover:text-text'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowRegister(true)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
        >
          에이전트 등록
        </button>
      </div>

      <div className="bg-surface border border-border rounded-lg p-5">
        {isLoading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : (
          <AgentTable
            items={members ?? []}
            onSuspend={(id) => suspend.mutate(id)}
            onReactivate={(id) => reactivate.mutate(id)}
            onRevoke={(id) => { if (confirm('이 에이전트를 영구 폐기하시겠습니까?')) revoke.mutate(id) }}
          />
        )}
      </div>

      {showRegister && (
        <AgentRegisterForm
          onClose={() => setShowRegister(false)}
          onTokenCreated={(token) => { setShowRegister(false); setCreatedToken(token) }}
        />
      )}

      {/* 토큰 표시 모달 */}
      {createdToken && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold mb-4">에이전트 토큰 발급 완료</h3>
            <p className="text-[13px] text-warning mb-3">이 토큰은 다시 확인할 수 없습니다. 반드시 복사해 두세요.</p>
            <div className="bg-bg border border-border rounded-lg p-3 font-mono text-[12px] break-all mb-4">
              {createdToken}
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(createdToken)}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
              >
                복사
              </button>
              <button
                onClick={() => setCreatedToken(null)}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover"
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
