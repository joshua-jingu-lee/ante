import { useState } from 'react'
import { useCreateMember, useMembers } from '../../hooks/useMembers'
import { ALL_SCOPES } from '../../types/member'

const DEFAULT_ORGS = ['default', 'strategy-lab', 'risk', 'treasury', 'operations']

interface AgentRegisterFormProps {
  onClose: () => void
  onTokenCreated: (agentId: string, token: string) => void
}

const AGENT_ID_PATTERN = /^[a-z0-9][a-z0-9-]*$/

export default function AgentRegisterForm({ onClose, onTokenCreated }: AgentRegisterFormProps) {
  const [memberId, setMemberId] = useState('')
  const [name, setName] = useState('')
  const [org, setOrg] = useState('default')
  const [scopes, setScopes] = useState<string[]>([])
  const createMember = useCreateMember()

  const memberIdError = memberId.length > 0 && !AGENT_ID_PATTERN.test(memberId)
    ? '영문 소문자, 숫자, 하이픈만 사용 가능하며 첫 글자는 영문 소문자 또는 숫자여야 합니다'
    : ''
  const isFormValid = memberId.length > 0 && !memberIdError

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
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-[18px] font-bold mb-5">에이전트 등록</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Agent ID</label>
            <input value={memberId} onChange={(e) => setMemberId(e.target.value)} placeholder="strategy-dev-03" className={`w-full bg-bg border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none ${memberIdError ? 'border-negative focus:border-negative' : 'border-border focus:border-primary'}`} required />
            {memberIdError ? (
              <div className="text-[12px] text-negative mt-1">{memberIdError}</div>
            ) : (
              <div className="text-[12px] text-text-muted mt-1">영문 소문자, 숫자, 하이픈만 사용 가능</div>
            )}
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="전략 리서치 3호" className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary" required />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">소속 (org)</label>
            <input
              value={org}
              onChange={(e) => setOrg(e.target.value)}
              list="org-options"
              placeholder="소속을 입력하거나 선택하세요"
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
            />
            <datalist id="org-options">
              {orgOptions.map((o) => (
                <option key={o} value={o} />
              ))}
            </datalist>
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
            <button type="submit" disabled={createMember.isPending || !isFormValid} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50">등록</button>
          </div>
        </form>
      </div>
    </div>
  )
}
