import { useState } from 'react'

export default function HintTooltip({ text }: { text: string }) {
  const [show, setShow] = useState(false)

  return (
    <span
      className="relative inline-flex items-center ml-1 cursor-help"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span className="w-4 h-4 rounded-full bg-[rgba(139,143,163,0.15)] text-text-muted text-[11px] font-bold flex items-center justify-center">
        ?
      </span>
      {show && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-surface border border-border rounded-lg text-[12px] text-text-muted whitespace-nowrap z-50 shadow-lg">
          {text}
        </span>
      )}
    </span>
  )
}
