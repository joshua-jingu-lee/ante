import { useState, useEffect, useCallback, useSyncExternalStore } from 'react'

interface ToastItem {
  id: number
  message: string
  type: 'error' | 'success' | 'warning'
}

let toastId = 0
let toasts: ToastItem[] = []
const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((l) => l())
}

export function showToast(message: string, type: ToastItem['type'] = 'error') {
  const id = ++toastId
  toasts = [...toasts, { id, message, type }]
  notify()
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id)
    notify()
  }, 5000)
}

function useToasts() {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => toasts,
  )
}

export default function ToastContainer() {
  const items = useToasts()

  const dismiss = useCallback((id: number) => {
    toasts = toasts.filter((t) => t.id !== id)
    notify()
  }, [])

  if (items.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 max-w-[400px]">
      {items.map((toast) => (
        <ToastMessage key={toast.id} toast={toast} onDismiss={dismiss} />
      ))}
    </div>
  )
}

function ToastMessage({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true))
  }, [])

  const bgColor =
    toast.type === 'error'
      ? 'bg-negative-bg border-negative'
      : toast.type === 'warning'
        ? 'bg-warning-bg border-warning'
        : 'bg-positive-bg border-positive'

  return (
    <div
      className={`${bgColor} border rounded-lg px-4 py-3 text-[13px] text-text shadow-[0_4px_12px_rgba(0,0,0,0.3)] flex items-start gap-2 transition-all duration-200 ${visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-4'}`}
    >
      <span className="flex-1 break-words">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="bg-transparent border-none text-text-muted cursor-pointer text-[16px] p-0 leading-none hover:text-text"
      >
        x
      </button>
    </div>
  )
}
