import { ArrowUp, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

const MAX_LENGTH = 2000 // Matches ChatRequest.question max_length in the API.
const MAX_HEIGHT_PX = 200

interface MessageComposerProps {
  isLoading: boolean
  onSend: (question: string) => boolean
}

export function MessageComposer({ isLoading, onSend }: MessageComposerProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canSend = value.trim().length > 0 && !isLoading

  // Grow with the content up to a maximum height.
  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [value])

  const submit = () => {
    if (!canSend) return
    if (onSend(value)) setValue('')
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    submit()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative">
      <label htmlFor="question" className="sr-only">
        Ask a question about a customer, loan, or document
      </label>
      <div className="flex items-end gap-2 rounded-2xl border border-line-strong bg-white p-2 shadow-[0_1px_2px_rgba(15,27,61,0.04),0_4px_16px_rgba(15,27,61,0.05)] transition-shadow focus-within:border-accent/50 focus-within:ring-4 focus-within:ring-accent/10">
        <textarea
          id="question"
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          maxLength={MAX_LENGTH}
          placeholder="Ask about a customer, loan, or document…"
          aria-describedby="composer-hint"
          className="max-h-[200px] min-h-[40px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[15px] leading-6 text-ink placeholder:text-muted/80 focus:outline-none focus-visible:outline-none"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label={isLoading ? 'Waiting for the assistant' : 'Send question'}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
        >
          {isLoading ? (
            <LoaderCircle className="h-[18px] w-[18px] animate-spin" aria-hidden />
          ) : (
            <ArrowUp className="h-[18px] w-[18px]" aria-hidden />
          )}
        </button>
      </div>
      <p id="composer-hint" className="sr-only">
        Press Enter to send and Shift+Enter for a new line.
      </p>
    </form>
  )
}
