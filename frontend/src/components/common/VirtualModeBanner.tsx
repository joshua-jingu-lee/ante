interface VirtualModeBannerProps {
  isVirtual: boolean
}

export default function VirtualModeBanner({ isVirtual }: VirtualModeBannerProps) {
  if (!isVirtual) return null

  return (
    <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg bg-info-bg border border-info/25 text-info text-[13px] mb-4">
      <span className="text-[15px]">&#9432;</span>
      <span>가상 거래 계좌입니다. 표시된 손익은 시뮬레이션 결과입니다.</span>
    </div>
  )
}
