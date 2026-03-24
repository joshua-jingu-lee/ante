const VARIANT_CLASSES: Record<string, string> = {
  positive: 'bg-positive-bg text-positive',
  negative: 'bg-negative-bg text-negative',
  warning: 'bg-warning-bg text-warning',
  info: 'bg-info-bg text-info',
  muted: 'bg-muted-bg text-text-muted',
  primary: 'bg-positive-bg text-primary',
}

interface StatusBadgeProps {
  variant: keyof typeof VARIANT_CLASSES
  children: React.ReactNode
}

export default function StatusBadge({ variant, children }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-[10px] text-[11px] font-semibold ${VARIANT_CLASSES[variant] || VARIANT_CLASSES.muted}`}>
      {children}
    </span>
  )
}
