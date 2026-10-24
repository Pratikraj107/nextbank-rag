import type { LucideIcon } from 'lucide-react'
import { ArrowUpRight, BadgeEuro, CircleHelp, FileCheck2, GitCompareArrows, Users } from 'lucide-react'

interface Suggestion {
  question: string
  purpose: string
  icon: LucideIcon
}

const SUGGESTIONS: Suggestion[] = [
  {
    question: "What is Lotte van Dijk's annual gross salary?",
    purpose: 'Salary fact',
    icon: BadgeEuro,
  },
  {
    question: "What is Thomas de Boer's monthly gross salary?",
    purpose: 'Another customer',
    icon: Users,
  },
  {
    question:
      "Does Lotte van Dijk's employment agreement confirm that she has worked at her current employer for at least 10 years?",
    purpose: 'Verify a claim',
    icon: FileCheck2,
  },
  {
    question:
      "Does the credit analyst note for loan NB-LOAN-2101 confirm that Thomas de Boer's document review is pending?",
    purpose: 'Identifier conflict',
    icon: GitCompareArrows,
  },
  {
    question: "What is Lotte van Dijk's favorite color?",
    purpose: 'Insufficient evidence',
    icon: CircleHelp,
  },
]

interface SuggestedQuestionsProps {
  disabled: boolean
  onSelect: (question: string) => void
}

export function SuggestedQuestions({ disabled, onSelect }: SuggestedQuestionsProps) {
  return (
    <section aria-labelledby="suggestions-heading">
      <h3 id="suggestions-heading" className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">
        Try a question
      </h3>
      <ul className="grid gap-2.5 sm:grid-cols-2">
        {SUGGESTIONS.map(({ question, purpose, icon: Icon }) => (
          <li key={question}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSelect(question)}
              className="group flex h-full w-full flex-col gap-2 rounded-xl border border-line bg-white p-3.5 text-left shadow-[0_1px_2px_rgba(15,27,61,0.04)] transition hover:-translate-y-px hover:border-accent/30 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0"
            >
              <span className="flex items-center justify-between text-xs font-medium text-muted">
                <span className="inline-flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 text-accent" aria-hidden />
                  {purpose}
                </span>
                <ArrowUpRight
                  className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100"
                  aria-hidden
                />
              </span>
              <span className="text-sm leading-snug text-ink">{question}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
