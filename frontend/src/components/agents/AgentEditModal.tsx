import { useState, useEffect } from 'react'
import Modal from '../common/Modal'
import { ALL_SCOPES, type MemberDetail } from '../../types/member'

interface AgentEditModalProps {
  open: boolean
  member: MemberDetail
  onClose: () => void
  onSave: (data: { name: string; org: string; scopes: string[] }) => void
  isPending?: boolean
}

export default function AgentEditModal({ open, member, onClose, onSave, isPending }: AgentEditModalProps) {
  const [name, setName] = useState(member.name)
  const [org, setOrg] = useState(member.org)
  const [scopes, setScopes] = useState<string[]>([...member.scopes])

  useEffect(() => {
    if (open) {
      setName(member.name)
      setOrg(member.org)
      setScopes([...member.scopes])
    }
  }, [open, member])

  const toggleScope = (scope: string) => {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    )
  }

  const handleSave = () => {
    onSave({ name: name.trim(), org: org.trim(), scopes })
  }

  return (
    <Modal open={open} onClose={onClose}>
      <div className="text-[16px] font-semibold mb-5">정보 수정</div>

      <div className="mb-4">
        <label className="block text-[12px] font-semibold text-text-muted mb-1.5">Agent ID</label>
        <div className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-text text-[13px] font-mono opacity-60">
          {member.member_id}
        </div>
      </div>

      <div className="mb-4">
        <label className="block text-[12px] font-semibold text-text-muted mb-1.5">이름</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-text text-[13px] focus:outline-none focus:border-primary"
        />
      </div>

      <div className="mb-4">
        <label className="block text-[12px] font-semibold text-text-muted mb-1.5">소속 (org)</label>
        <input
          type="text"
          value={org}
          onChange={(e) => setOrg(e.target.value)}
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-text text-[13px] focus:outline-none focus:border-primary"
        />
      </div>

      <div className="mb-5">
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

      <div className="flex justify-end gap-2 pt-4 border-t border-border">
        <button
          onClick={onClose}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover"
        >
          취소
        </button>
        <button
          onClick={handleSave}
          disabled={isPending || !name.trim()}
          className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-white border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50"
        >
          저장
        </button>
      </div>
    </Modal>
  )
}
