// Client for the read-only document endpoints (src/api/documents.py).

import { getJson, isRecord, malformed, optionalNumber, optionalString } from './api'
import { humanize } from './sources'

// ------------------------------------------------------------
// Types mirroring the backend response models
// ------------------------------------------------------------

export interface DocumentSummary {
  id: string
  filename: string
  source: string
  sourceType: string | null
  documentType: string | null
  customerId: string | null
  loanId: string | null
  /** Set only for CSV rows, where one file holds several documents. */
  rowNumber: number | null
  chunkCount: number
}

export interface FacetValue {
  value: string
  count: number
}

export interface DocumentFacets {
  documentTypes: FacetValue[]
  customerIds: FacetValue[]
  loanIds: FacetValue[]
}

export interface DocumentPage {
  items: DocumentSummary[]
  /** Documents matching the filters. */
  total: number
  /** Documents in the whole library. */
  libraryTotal: number
  page: number
  pageSize: number
  totalPages: number
  facets: DocumentFacets
}

export interface DocumentDetail extends DocumentSummary {
  content: string
  /** Fields extracted during ingestion; keys vary by document type. */
  metadata: Record<string, unknown>
}

export interface DocumentChunk {
  chunkId: string | null
  chunkIndex: number
  content: string
  documentType: string | null
  customerId: string | null
  loanId: string | null
}

export interface DocumentQuery {
  search: string
  documentType: string
  customerId: string
  loanId: string
  page: number
  pageSize: number
}

// ------------------------------------------------------------
// Parsing
// ------------------------------------------------------------

function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  if (typeof value !== 'string') throw malformed(`"${key}" is missing.`)
  return value
}

function requireNumber(record: Record<string, unknown>, key: string): number {
  const value = optionalNumber(record[key])
  if (value === null) throw malformed(`"${key}" is missing.`)
  return value
}

function parseSummary(value: unknown): DocumentSummary {
  if (!isRecord(value)) throw malformed('a document entry is not an object.')

  return {
    id: requireString(value, 'id'),
    filename: requireString(value, 'filename'),
    source: requireString(value, 'source'),
    sourceType: optionalString(value.source_type),
    documentType: optionalString(value.document_type),
    customerId: optionalString(value.customer_id),
    loanId: optionalString(value.loan_id),
    rowNumber: optionalNumber(value.row_number),
    chunkCount: requireNumber(value, 'chunk_count'),
  }
}

function parseFacets(value: unknown): FacetValue[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    value: String(item.value),
    count: optionalNumber(item.count) ?? 0,
  }))
}

function parsePage(value: unknown): DocumentPage {
  if (!isRecord(value) || !Array.isArray(value.items)) throw malformed('expected a document list.')
  const facets = isRecord(value.facets) ? value.facets : {}

  return {
    items: value.items.map(parseSummary),
    total: requireNumber(value, 'total'),
    libraryTotal: requireNumber(value, 'library_total'),
    page: requireNumber(value, 'page'),
    pageSize: requireNumber(value, 'page_size'),
    totalPages: requireNumber(value, 'total_pages'),
    facets: {
      documentTypes: parseFacets(facets.document_types),
      customerIds: parseFacets(facets.customer_ids),
      loanIds: parseFacets(facets.loan_ids),
    },
  }
}

function parseDetail(value: unknown): DocumentDetail {
  if (!isRecord(value)) throw malformed('expected a document.')

  return {
    ...parseSummary(value),
    content: typeof value.content === 'string' ? value.content : '',
    metadata: isRecord(value.metadata) ? value.metadata : {},
  }
}

function parseChunks(value: unknown): DocumentChunk[] {
  if (!isRecord(value) || !Array.isArray(value.chunks)) throw malformed('expected a chunk list.')

  return value.chunks.map((chunk) => {
    if (!isRecord(chunk)) throw malformed('a chunk is not an object.')
    return {
      chunkId: optionalString(chunk.chunk_id),
      chunkIndex: requireNumber(chunk, 'chunk_index'),
      content: requireString(chunk, 'content'),
      documentType: optionalString(chunk.document_type),
      customerId: optionalString(chunk.customer_id),
      loanId: optionalString(chunk.loan_id),
    }
  })
}

// ------------------------------------------------------------
// Endpoints
// ------------------------------------------------------------

export async function listDocuments(query: DocumentQuery, signal?: AbortSignal): Promise<DocumentPage> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
  })
  if (query.search.trim()) params.set('q', query.search.trim())
  if (query.documentType) params.set('document_type', query.documentType)
  if (query.customerId) params.set('customer_id', query.customerId)
  if (query.loanId) params.set('loan_id', query.loanId)

  return parsePage(await getJson(`/api/documents?${params}`, signal))
}

export async function getDocument(id: string, signal?: AbortSignal): Promise<DocumentDetail> {
  return parseDetail(await getJson(`/api/documents/${encodeURIComponent(id)}`, signal))
}

export async function getDocumentChunks(id: string, signal?: AbortSignal): Promise<DocumentChunk[]> {
  return parseChunks(await getJson(`/api/documents/${encodeURIComponent(id)}/chunks`, signal))
}

/**
 * An editable question for the chat about one document. The chat API takes
 * only a question, so the agent still searches all documents.
 */
export function questionAbout(document: DocumentDetail): string {
  const type = document.documentType ? humanize(document.documentType).toLowerCase() : 'document'
  const row = document.rowNumber !== null ? ` (row ${document.rowNumber})` : ''
  const scope = document.loanId
    ? ` for loan ${document.loanId}`
    : document.customerId
      ? ` for customer ${document.customerId}`
      : ''
  return `What does the ${type} ${document.filename}${row}${scope} state?`
}
