import { lazy, Suspense } from 'react'

const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

export default function MarkdownBody({ content }: { content: string }) {
  return (
    <Suspense fallback={<div className="text-[13px] text-text-muted whitespace-pre-wrap leading-relaxed">{content}</div>}>
      <MarkdownRenderer content={content} />
    </Suspense>
  )
}
