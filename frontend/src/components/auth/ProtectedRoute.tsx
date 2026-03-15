import { Navigate } from 'react-router-dom'
import { useUser } from '../../hooks/useAuth'
import LoadingSpinner from '../common/LoadingSpinner'

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, isError } = useUser()

  if (isLoading) {
    return <LoadingSpinner className="min-h-screen" />
  }

  if (isError || !user) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
