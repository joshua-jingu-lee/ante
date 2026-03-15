import { Navigate } from 'react-router-dom'
import { useUser } from '../hooks/useAuth'
import LoginForm from '../components/auth/LoginForm'

export default function Login() {
  const { data: user, isLoading } = useUser()

  if (!isLoading && user) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <div className="bg-surface border border-border rounded-lg p-10 w-[400px] text-center">
        <div className="flex items-center justify-center gap-0 mb-1">
          <img src="/logo-a.svg" alt="A" className="w-14 h-14" />
          <img src="/logo-n.svg" alt="N" className="w-14 h-14" />
          <img src="/logo-t.svg" alt="T" className="w-14 h-14" />
          <img src="/logo-e.svg" alt="E" className="w-14 h-14" />
        </div>
        <div className="text-[13px] text-text-muted mb-8">AI-Native Trading Engine</div>
        <LoginForm />
      </div>
    </div>
  )
}
