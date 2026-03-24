import { useState } from 'react'
import { useMemberControl } from '../../hooks/useMembers'

interface ChangePasswordModalProps {
  memberId: string
  onClose: () => void
}

export default function ChangePasswordModal({ memberId, onClose }: ChangePasswordModalProps) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const { changePassword } = useMemberControl()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword.length < 4) {
      setError('새 비밀번호는 최소 4자 이상이어야 합니다')
      return
    }

    if (newPassword !== confirmPassword) {
      setError('새 비밀번호가 일치하지 않습니다')
      return
    }

    changePassword.mutate(
      { id: memberId, oldPassword, newPassword },
      {
        onSuccess: () => setSuccess(true),
        onError: (err) => {
          const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
            ?? '비밀번호 변경에 실패했습니다'
          setError(message)
        },
      },
    )
  }

  if (success) {
    return (
      <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
        <div className="bg-surface border border-border rounded-lg p-6 w-[400px] text-center">
          <h3 className="text-[18px] font-bold mb-4 text-positive">비밀번호 변경 완료</h3>
          <p className="text-[13px] text-text-muted mb-5">
            <span className="font-semibold text-text">{memberId}</span>의 비밀번호가 변경되었습니다.
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover"
          >
            닫기
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[400px]">
        <h2 className="text-[18px] font-bold mb-5">비밀번호 변경</h2>
        <p className="text-[13px] text-text-muted mb-4">
          <span className="font-semibold text-text">{memberId}</span>
        </p>
        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">현재 비밀번호</label>
            <input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
              required
              autoFocus
            />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">새 비밀번호</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
              required
            />
          </div>
          <div className="mb-4">
            <label className="block text-[12px] font-semibold text-text-muted mb-1.5">새 비밀번호 확인</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] focus:outline-none focus:border-primary"
              required
            />
          </div>
          {error && (
            <div className="text-[13px] text-negative mb-4">{error}</div>
          )}
          <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={changePassword.isPending}
              className="px-4 py-2 rounded-lg text-[13px] font-medium bg-primary text-on-primary border-none cursor-pointer hover:bg-primary-hover disabled:opacity-50"
            >
              {changePassword.isPending ? '변경 중...' : '변경'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
