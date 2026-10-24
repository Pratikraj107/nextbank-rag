import type { ReactNode } from 'react'

// A deliberately small Markdown subset rendered as React elements, so the
// backend's text is never injected as HTML.
//   - blank-line separated paragraphs, single line breaks preserved
//   - "-", "*" or "•" bullet lists and "1." numbered lists
//   - "#" headings (rendered as bold lines), **bold** and `code`
//   - citation labels such as [S1], [S1][S2] and [S1, S2]

const INLINE_PATTERN = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[S\d+(?:\s*,\s*S\d+)*\])/g
const CITATION_PATTERN = /^\[(S\d+(?:\s*,\s*S\d+)*)\]$/
const BULLET_PATTERN = /^\s*[-*•]\s+/
const NUMBERED_PATTERN = /^\s*\d+[.)]\s+/
const HEADING_PATTERN = /^#{1,6}\s+/

interface CitationProps {
  label: string
  sourceCount: number
  onSelect?: (index: number) => void
}

function Citation({ label, sourceCount, onSelect }: CitationProps) {
  const index = Number(label.slice(1)) - 1
  const hasEntry = index >= 0 && index < sourceCount
  const className =
    'mx-0.5 inline-flex items-center rounded-md px-1.5 py-px align-[1px] text-[11px] font-semibold leading-4 tabular-nums'

  if (hasEntry && onSelect) {
    return (
      <button
        type="button"
        onClick={() => onSelect(index)}
        className={`${className} bg-accent-soft text-accent ring-1 ring-accent/15 transition-colors hover:bg-accent hover:text-white`}
        aria-label={`Show source entry ${label}`}
        title={`Show source entry ${label}`}
      >
        {label}
      </button>
    )
  }

  return (
    <span
      className={`${className} bg-slate-100 text-ink-soft ring-1 ring-line`}
      title={hasEntry ? `Citation ${label}` : `No source entry ${label} was returned`}
    >
      {label}
    </span>
  )
}

interface AnswerTextProps {
  text: string
  sourceCount: number
  onCitation?: (index: number) => void
}

export function AnswerText({ text, sourceCount, onCitation }: AnswerTextProps) {
  const renderInline = (value: string, keyPrefix: string): ReactNode[] =>
    value.split(INLINE_PATTERN).map((part, i) => {
      const key = `${keyPrefix}-${i}`

      if (!part) return null

      const citation = CITATION_PATTERN.exec(part)
      if (citation) {
        return citation[1].split(/\s*,\s*/).map((label) => (
          <Citation key={`${key}-${label}`} label={label} sourceCount={sourceCount} onSelect={onCitation} />
        ))
      }

      if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
        return (
          <strong key={key} className="font-semibold text-ink">
            {renderInline(part.slice(2, -2), key)}
          </strong>
        )
      }

      if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
        return (
          <code key={key} className="rounded bg-slate-100 px-1 py-px font-mono text-[0.85em]">
            {part.slice(1, -1)}
          </code>
        )
      }

      return part
    })

  const blocks = text.trim().split(/\n\s*\n/)

  return (
    <div className="space-y-3 text-[15px] leading-relaxed text-ink [overflow-wrap:anywhere]">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').filter((line) => line.trim() !== '')
        const key = `b${blockIndex}`

        if (lines.length === 0) return null

        if (lines.every((line) => BULLET_PATTERN.test(line))) {
          return (
            <ul key={key} className="list-disc space-y-1 pl-5 marker:text-muted">
              {lines.map((line, i) => (
                <li key={i}>{renderInline(line.replace(BULLET_PATTERN, ''), `${key}-${i}`)}</li>
              ))}
            </ul>
          )
        }

        if (lines.every((line) => NUMBERED_PATTERN.test(line))) {
          return (
            <ol key={key} className="list-decimal space-y-1 pl-5 marker:text-muted">
              {lines.map((line, i) => (
                <li key={i}>{renderInline(line.replace(NUMBERED_PATTERN, ''), `${key}-${i}`)}</li>
              ))}
            </ol>
          )
        }

        if (lines.length === 1 && HEADING_PATTERN.test(lines[0])) {
          return (
            <p key={key} className="font-semibold text-ink">
              {renderInline(lines[0].replace(HEADING_PATTERN, ''), key)}
            </p>
          )
        }

        return (
          <p key={key}>
            {lines.map((line, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {renderInline(line, `${key}-${i}`)}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}
