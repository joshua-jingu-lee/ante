import { useState } from 'react'
import { useMembers, useMemberControl } from '../hooks/useMembers'
import MemberCard from '../components/agents/MemberCard'
import AgentRegisterForm from '../components/agents/AgentRegisterForm'
import { TableSkeleton } from '../components/common/Skeleton'

export default function Agents() {
  const [orgFilter, setOrgFilter] = useState<string>('all')
  const [showRegister, setShowRegister] = useState(false)
  const [createdToken, setCreatedToken] = useState<string | null>(null)

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

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
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
        <button
          onClick={() => setShowRegister(true)}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover"
        >
          멤버 등록
        </button>
      </div>

      {isLoading ? (
        <TableSkeleton rows={3} cols={3} />
      ) : (
        <>
          {/* Human 멤버 섹션 */}
          <div className="mb-8">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-text-muted mb-4">
              Human 멤버
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{filterByOrg(humans).length}</span>
            </div>
            {filterByOrg(humans).length === 0 ? (
              <div className="text-[13px] text-text-muted py-6 text-center">Human 멤버가 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
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
              Agent 멤버
              <span className="bg-border text-text text-[12px] font-medium px-2 py-0.5 rounded-full">{filterByOrg(agents).length}</span>
            </div>
            {filterByOrg(agents).length === 0 ? (
              <div className="text-[13px] text-text-muted py-6 text-center">Agent 멤버가 없습니다</div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
                {filterByOrg(agents).map((m) => (
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
          onTokenCreated={(token) => { setShowRegister(false); setCreatedToken(token) }}
        />
      )}

      {createdToken && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold mb-4">에이전트 토큰 발급 완료</h3>
            <p className="text-[13px] text-warning mb-3">이 토큰은 다시 확인할 수 없습니다. 반드시 복사해 두세요.</p>
            <div className="bg-bg border border-border rounded-lg p-3 font-mono text-[12px] break-all mb-4">
              {createdToken}
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => navigator.clipboard.writeText(createdToken)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover">복사</button>
              <button onClick={() => setCreatedToken(null)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">닫기</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
