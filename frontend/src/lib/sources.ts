import type { ChatSource } from './api'

export interface SourceEntry {
  /** Position in the backend's `sources` array (0-based). */
  index: number
  /** Citation label the backend assigns to this position, e.g. "S1". */
  label: string
  chunkIndex: number | null
}

export interface SourceGroup {
  key: string
  source: string
  filename: string
  folder: string
  documentType: string | null
  customerId: string | null
  loanId: string | null
  entries: SourceEntry[]
}

/** "data/raw/NB-LOAN-2101/pdf/03_payslip.pdf" -> "03_payslip.pdf" */
export function fileName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.at(-1) ?? path
}

/** "data/raw/NB-LOAN-2101/pdf/03_payslip.pdf" -> "data/raw/NB-LOAN-2101/pdf" */
export function folderName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.slice(0, -1).join('/')
}

const ACRONYMS = new Set(['csv', 'sepa', 'id', 'iban', 'html', 'pdf'])

/** "existing_loan_statement" -> "Existing loan statement", "csv_record" -> "CSV record" */
export function humanize(value: string): string {
  const words = value
    .replace(/[_-]+/g, ' ')
    .trim()
    .split(/\s+/)
    .map((word) => (ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word.toLowerCase()))
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * Group chunk-level source entries by file + customer + loan, keeping
 * the original order of first appearance.
 */
export function groupSources(sources: ChatSource[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>()

  sources.forEach((source, index) => {
    const key = [source.source, source.customer_id ?? '', source.loan_id ?? ''].join('|')

    let group = groups.get(key)

    if (!group) {
      group = {
        key,
        source: source.source,
        filename: fileName(source.source),
        folder: folderName(source.source),
        documentType: source.document_type,
        customerId: source.customer_id,
        loanId: source.loan_id,
        entries: [],
      }
      groups.set(key, group)
    }

    group.entries.push({
      index,
      label: `S${index + 1}`,
      chunkIndex: source.chunk_index,
    })
  })

  return [...groups.values()]
}
