import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

const components: Components = {
  h1: ({ children }) => <h1 className="text-[15px] font-bold text-text mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-[14px] font-semibold text-text mb-2">{children}</h2>,
  h3: ({ children }) => <h3 className="text-[13px] font-semibold text-text mb-3">{children}</h3>,
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="text-text font-semibold">{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  del: ({ children }) => <del>{children}</del>,
  a: ({ href, children }) => <a href={href} className="text-primary hover:underline">{children}</a>,
  ul: ({ children }) => <ul className="pl-5 mb-3 list-disc">{children}</ul>,
  ol: ({ children }) => <ol className="pl-5 mb-3 list-decimal">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-3 border-border pl-3.5 py-2 mb-3 text-text-muted italic">{children}</blockquote>
  ),
  code: ({ className, children }) => {
    const isBlock = className?.includes('language-')
    if (isBlock) {
      return (
        <pre className="bg-bg-elevated p-3 rounded text-[12px] overflow-x-auto mb-3">
          <code>{children}</code>
        </pre>
      )
    }
    return <code className="bg-bg-elevated px-1.5 py-0.5 rounded text-[12px]">{children}</code>
  },
  pre: ({ children }) => <>{children}</>,
  table: ({ children }) => (
    <div className="overflow-x-auto mb-3">
      <table className="w-full border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr>{children}</tr>,
  th: ({ children }) => (
    <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">{children}</th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2 border-b border-border text-[13px]">{children}</td>
  ),
  hr: () => <hr className="border-t border-border my-3" />,
}

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="text-[13px] text-text-muted leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
