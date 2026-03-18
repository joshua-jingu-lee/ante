import { useState } from 'react'
import { useMembers, useMemberControl } from '../hooks/useMembers'
import MemberCard from '../components/agents/MemberCard'
import AgentRegisterForm from '../components/agents/AgentRegisterForm'
import { TableSkeleton } from '../components/common/Skeleton'
import type { MemberStatus } from '../types/member'

const STATUS_TABS: { label: string; value: MemberStatus | 'all' }[] = [
  { label: '전체', value: 'all' },
  { label: 'active', value: 'active' },
  { label: 'suspended', value: 'suspended' },
  { label: 'revoked', value: 'revoked' },
]

export default function Agents() {
  const [orgFilter, setOrgFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<MemberStatus | 'all'>('all')
  const [showRegister, setShowRegister] = useState(false)
  const [createdToken, setCreatedToken] = useState<{ agentId: string; token: string } | null>(null)

  const { data: allMembers, isLoading } = useMembers({})
  const { data: humanMembers } = useMembers({ type: 'human' })
  const { data: agentMembers } = useMembers({ type: 'agent' })
  const { suspend, reactivate, revoke } = useMemberControl()

  const humans = humanMembers ?? []
  const agents = agentMembers ?? []

  // 소속 목록 추출
  const allItems = allMembers ?? []
  const orgs = Array.from(new Set(allItems.map((m) => m.org).filter(Boolean)))

  const filterByOrg = (items: typeof allItems) =>
    orgFilter === 'all' ? items : items.filter((m) => m.org === orgFilter)

  const filterAgents = (items: typeof allItems) => {
    let filtered = filterByOrg(items)
    if (statusFilter !== 'all') {
      filtered = filtered.filter((m) => m.status === statusFilter)
    }
    return filtered
  }

  return (
    <>
      {isLoading ? (
        <TableSkeleton rows={3} cols={3} />
      ) : (
        <>
          {/* Human 멤버 섹션 */}
          <div className="mb-8">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted mb-4">
              {'👤'} Human 멤버
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{humans.length}</span>
            </div>
            {humans.length === 0 ? (
              <div className="text-[13px] text-text-muted py-6 text-center">Human 멤버가 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {filterByOrg(humans).map((m) => (
                  <MemberCard
                    key={m.member_id}
                    member={m}
                    onSuspend={m.member_id !== 'owner' ? (id) => suspend.mutate(id) : undefined}
                    onChangePassword={() => {/* TODO: 비밀번호 변경 모달 연결 */}}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Agent 멤버 섹션 */}
          <div className="mb-8">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted mb-4">
              {'☯'} Agent 멤버
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{agents.length}</span>
              <div className="ml-auto">
                <button
                  onClick={() => setShowRegister(true)}
                  className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
                >
                  + 에이전트 등록
                </button>
              </div>
            </div>

            {/* 필터 영역: 상태 탭 + 소속 셀렉트 */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex gap-1">
                {STATUS_TABS.map((tab) => (
                  <button
                    key={tab.value}
                    onClick={() => setStatusFilter(tab.value)}
                    className={`px-3 py-1.5 rounded-lg text-[13px] font-medium border cursor-pointer transition-colors ${
                      statusFilter === tab.value
                        ? 'bg-primary text-white border-primary'
                        : 'bg-transparent text-text-muted border-border hover:bg-surface-hover'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <select
                value={orgFilter}
                onChange={(e) => setOrgFilter(e.target.value)}
                className="bg-bg border border-border rounded-lg px-3 py-1.5 text-text text-[13px] cursor-pointer"
              >
                <option value="all">전체 소속</option>
                {orgs.map((org) => (
                  <option key={org} value={org}>{org}</option>
                ))}
              </select>
            </div>

            {filterAgents(agents).length === 0 ? (
              <div className="text-[13px] text-text-muted py-6 text-center">Agent 멤버가 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4">
                {filterAgents(agents).map((m) => (
                  <MemberCard
                    key={m.member_id}
                    member={m}
                    onSuspend={(id) => suspend.mutate(id)}
                    onReactivate={(id) => reactivate.mutate(id)}
                    onRevoke={(id) => { if (confirm('이 에이전트를 영구 폐기하시겠습니까?')) revoke.mutate(id) }}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {showRegister && (
        <AgentRegisterForm
          onClose={() => setShowRegister(false)}
          onTokenCreated={(agentId, token) => { setShowRegister(false); setCreatedToken({ agentId, token }) }}
        />
      )}

      {/* 토큰 표시 모달 — 목업 tokenModal 기준 */}
      {createdToken && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px] text-center">
            <h3 className="text-[18px] font-bold mb-4 text-positive">{'✓'} 에이전트 등록 완료</h3>

            <div className="mb-2">
              <div className="text-[12px] font-semibold text-text-muted">Agent ID</div>
              <div className="text-[16px] font-semibold">{createdToken.agentId}</div>
            </div>

            <div className="my-5">
              <div className="text-[12px] font-semibold text-text-muted">발급된 토큰</div>
              <div className="bg-bg border border-border rounded-lg p-3.5 font-mono text-[13px] break-all text-left mt-2">
                {createdToken.token}
              </div>
            </div>

            <div className="bg-warning-bg text-warning p-3 rounded-lg text-[13px] mb-5 text-left">
              {'⚠'} 이 토큰은 다시 표시되지 않습니다. 안전한 곳에 복사해 두세요.
            </div>

            <div className="flex justify-center gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(createdToken.token)}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
              >
                토큰 복사
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
