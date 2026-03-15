import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getMembers, getMemberDetail, createMember, suspendMember, reactivateMember, revokeMember, rotateToken, updateScopes } from '../api/members'
import type { MemberCreateRequest } from '../types/member'

export function useMembers(params?: { type?: string; org?: string; status?: string }) {
  return useQuery({
    queryKey: ['members', params],
    queryFn: () => getMembers(params),
  })
}

export function useMemberDetail(id: string) {
  return useQuery({
    queryKey: ['members', id],
    queryFn: () => getMemberDetail(id),
    enabled: !!id,
  })
}

export function useCreateMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: MemberCreateRequest) => createMember(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members'] }),
  })
}

export function useMemberControl() {
  const queryClient = useQueryClient()
  return {
    suspend: useMutation({
      mutationFn: suspendMember,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members'] }),
    }),
    reactivate: useMutation({
      mutationFn: reactivateMember,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members'] }),
    }),
    revoke: useMutation({
      mutationFn: revokeMember,
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members'] }),
    }),
    rotateToken: useMutation({
      mutationFn: rotateToken,
    }),
    updateScopes: useMutation({
      mutationFn: ({ id, scopes }: { id: string; scopes: string[] }) => updateScopes(id, scopes),
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members'] }),
    }),
  }
}
