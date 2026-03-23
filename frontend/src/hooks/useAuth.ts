import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { login, logout, getMe } from '../api/auth'
import type { LoginRequest } from '../types/auth'

export function useUser() {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: getMe,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  return useMutation({
    mutationFn: (data: LoginRequest) => login(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      const redirect = searchParams.get('redirect') || '/treasury'
      navigate(redirect, { replace: true })
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear()
      navigate('/login', { replace: true })
    },
  })
}
