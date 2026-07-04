import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Рендер markdown-ответа с кликабельными inline-цитатами [1], [2] ...
export function AnswerMarkdown({
  markdown,
  onCite,
}: {
  markdown: string
  onCite: (index: number) => void
}) {
  // Разбиваем текст на сегменты по паттерну [n] и делаем кнопки.
  const renderWithCitations = useMemo(
    () =>
      function CiteText({ children }: { children?: React.ReactNode }) {
        const out: React.ReactNode[] = []
        let key = 0
        const walk = (node: React.ReactNode) => {
          if (typeof node === 'string') {
            const parts = node.split(/(\[\d+\])/g)
            for (const p of parts) {
              const m = p.match(/^\[(\d+)\]$/)
              if (m) {
                const idx = Number(m[1])
                out.push(
                  <button
                    key={`c-${key++}`}
                    onClick={() => onCite(idx)}
                    className="align-super text-[0.72em] font-semibold text-accent hover:text-accent-soft mx-0.5"
                    title={`Открыть источник [${idx}]`}
                  >
                    [{idx}]
                  </button>,
                )
              } else if (p) {
                out.push(<span key={`t-${key++}`}>{p}</span>)
              }
            }
          } else if (Array.isArray(node)) {
            node.forEach(walk)
          } else {
            out.push(node)
          }
        }
        walk(children)
        return <>{out}</>
      },
    [onCite],
  )

  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{renderWithCitations({ children })}</p>,
          li: ({ children }) => <li>{renderWithCitations({ children })}</li>,
          td: ({ children }) => <td>{renderWithCitations({ children })}</td>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}
