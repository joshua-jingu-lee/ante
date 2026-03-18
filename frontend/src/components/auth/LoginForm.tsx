import { useState } from 'react'
import { useLogin } from '../../hooks/useAuth'

export default function LoginForm() {
  const [memberId, setMemberId] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const loginMutation = useLogin()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    loginMutation.mutate({ member_id: memberId, password })
  }

  return (
    <form onSubmit={handleSubmit} className="text-left">
      {loginMutation.isError && (
        <div className="bg-negative-bg text-negative px-3.5 py-2.5 rounded-lg text-[13px] mb-4">
          ID 또는 패스워드가 올바르지 않습니다.
        </div>
      )}

      <div className="mb-4">
        <label className="block text-[12px] font-semibold text-text-muted mb-1.5">
          Member ID
        </label>
        <input
          type="text"
          value={memberId}
          onChange={(e) => setMemberId(e.target.value)}
          placeholder="owner"
          autoFocus
          className="w-full bg-bg border border-border rounded-lg py-3 px-3.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
        />
      </div>

      <div className="mb-4">
        <label className="block text-[12px] font-semibold text-text-muted mb-1.5">
          패스워드
        </label>
        <div className="relative">
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="패스워드를 입력하세요"
            className="w-full bg-bg border border-border rounded-lg py-3 px-3.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-3 top-1/2 -translate-y-1/2 bg-transparent border-none text-text-muted cursor-pointer text-[14px]"
            title="패스워드 표시"
          >
            {'\u{1F441}'}
          </button>
        </div>
      </div>

      <button
        type="submit"
        disabled={loginMutation.isPending || !memberId || !password}
        className="w-full inline-flex items-center justify-center py-3 bg-primary text-white rounded-lg text-[14px] font-semibold mt-2 hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border-none transition-colors duration-150"
      >
        {loginMutation.isPending ? '로그인 중...' : '로그인'}
      </button>
    </form>
  )
}
