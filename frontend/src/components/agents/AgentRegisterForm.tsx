import { useState } from 'react'
import { useCreateMember, useMembers } from '../../hooks/useMembers'
import { ALL_SCOPES } from '../../types/member'

const DEFAULT_ORGS = ['default', 'strategy-lab', 'risk', 'treasury', 'operations']

interface AgentRegisterFormProps {
  onClose: () => void
  onTokenCreated: (agentId: string, token: string) => void
}

export default function AgentRegisterForm({ onClose, onTokenCreated }: AgentRegisterFormProps) {
  const [memberId, setMemberId] = useState('')
  const [name, setName] = useState('')
  const [org, setOrg] = useState('default')
  const [scopes, setScopes] = useState<string[]>([])
  const createMember = useCreateMember()

  // 기존 소속 목록에서 동적으로 추출, 기본값과 병합
  const { data: allMembers } = useMembers({})
  const existingOrgs = Array.from(new Set((allMembers ?? []).map((m) => m.org).filter(Boolean)))
  const orgOptions = Array.from(new Set([...DEFAULT_ORGS, ...existingOrgs]))

  const toggleScope = (scope: string) => {
    setScopes((prev) => prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope])
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMember.mutate(
      { member_id: memberId, member_type: 'agent', name, org, scopes },
      { onSuccess: (data) => onTokenCreated(memberId, data.token) },
    )
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-[18px] font-bold mb-5">에이전트 등록</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Agent ID</label>
            <input value={memberId} onChange={(e) => setMemberId(e.target.value)} placeholder="strategy-dev-03" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
            <div className="text-[12px] text-text-muted mt-1">영문, 숫자, 하이픈만 사용 가능</div>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="전략 리서치 3호" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">소속 (org)</label>
            <select
              value={org}
              onChange={(e) => setOrg(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary cursor-pointer"
            >
              {orgOptions.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-2">권한 범위 (Scopes)</label>
            <div className="grid grid-cols-2 gap-2">
              {ALL_SCOPES.map((scope) => (
                <label key={scope} className="flex items-center gap-2 text-[13px] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={() => toggleScope(scope)}
                    className="accent-primary"
                  />
                  <span className="font-mono text-[12px]">{scope}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
            <button type="submit" disabled={createMember.isPending} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50">등록</button>
          </div>
        </form>
      </div>
    </div>
  )
}
