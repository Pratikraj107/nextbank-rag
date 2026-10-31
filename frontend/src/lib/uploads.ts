// Client for document upload and ingestion jobs (src/api/uploads.py).

import {
  API_BASE_URL,
  ApiError,
  getJson,
  isRecord,
  malformed,
  optionalNumber,
  optionalString,
  postJson,
} from './api'

export type JobStatus = 'uploaded' | 'processing' | 'ready' | 'failed'
export type StageStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface JobStage {
  name: string
  status: StageStatus
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  error: string | null
}

/** Labels for the backend's processing stages, in order. */
export const STAGE_LABELS: Record<string, string> = {
  validation: 'Upload validation',
  parsing: 'Text extraction',
  normalization: 'Classification and checks',
  chunking: 'Chunking',
  embedding: 'Embedding',
  indexing: 'Indexing and verification',
}

export interface UploadOptions {
  allowedExtensions: string[]
  maxUploadBytes: number
  customers: string[]
  loans: { loanId: string; customerId: string }[]
}

export interface IngestionJob {
  jobId: string
  documentId: string
  filename: string
  sizeBytes: number
  customerId: string
  loanId: string | null
  status: JobStatus
  step: string
  stepIndex: number
  stepCount: number
  attempts: number
  error: string | null
  warnings: string[]
  documentType: string | null
  chunkCount: number | null
  stages: JobStage[]
  failedStage: string | null
  /** Whether a failed job can be run again. */
  retryable: boolean
  createdAt: string
  finishedAt: string | null
  /** Upload to completion, or until now while still running. */
  durationMs: number | null
}

export interface FacetValue {
  value: string
  count: number
}

export interface JobPage {
  items: IngestionJob[]
  total: number
  page: number
  pageSize: number
  totalPages: number
  facets: { statuses: FacetValue[]; customerIds: FacetValue[]; documentTypes: FacetValue[] }
}

export interface JobQuery {
  status: string
  customerId: string
  documentType: string
  page: number
  pageSize: number
}

export interface UploadResult {
  job: IngestionJob
  duplicate: boolean
}

const STATUSES: JobStatus[] = ['uploaded', 'processing', 'ready', 'failed']
const STAGE_STATUSES: StageStatus[] = ['pending', 'running', 'completed', 'failed']

export const isTerminal = (status: JobStatus) => status === 'ready' || status === 'failed'

// ------------------------------------------------------------
// Parsing
// ------------------------------------------------------------

function parseJob(value: unknown): IngestionJob {
  if (!isRecord(value)) throw malformed('expected a job.')
  const status = value.status
  if (typeof status !== 'string' || !STATUSES.includes(status as JobStatus)) {
    throw malformed('the job status is not recognised.')
  }
  const jobId = optionalString(value.job_id)
  const documentId = optionalString(value.document_id)
  if (!jobId || !documentId) throw malformed('the job is missing its identifiers.')

  return {
    jobId,
    documentId,
    filename: optionalString(value.filename) ?? 'document',
    sizeBytes: optionalNumber(value.size_bytes) ?? 0,
    customerId: optionalString(value.customer_id) ?? '',
    loanId: optionalString(value.loan_id),
    status: status as JobStatus,
    step: optionalString(value.step) ?? '',
    stepIndex: optionalNumber(value.step_index) ?? 0,
    stepCount: optionalNumber(value.step_count) ?? 1,
    attempts: optionalNumber(value.attempts) ?? 0,
    error: optionalString(value.error),
    warnings: Array.isArray(value.warnings) ? value.warnings.filter((w): w is string => typeof w === 'string') : [],
    documentType: optionalString(value.document_type),
    chunkCount: optionalNumber(value.chunk_count),
    stages: Array.isArray(value.stages) ? value.stages.filter(isRecord).map(parseStage) : [],
    failedStage: optionalString(value.failed_stage),
    retryable: value.retryable === true,
    createdAt: optionalString(value.created_at) ?? '',
    finishedAt: optionalString(value.finished_at),
    durationMs: optionalNumber(value.duration_ms),
  }
}

function parseStage(value: Record<string, unknown>): JobStage {
  const status = STAGE_STATUSES.includes(value.status as StageStatus) ? (value.status as StageStatus) : 'pending'
  return {
    name: optionalString(value.name) ?? 'unknown',
    status,
    startedAt: optionalString(value.started_at),
    finishedAt: optionalString(value.finished_at),
    durationMs: optionalNumber(value.duration_ms),
    error: optionalString(value.error),
  }
}

function parseFacetList(value: unknown): FacetValue[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({ value: String(item.value), count: optionalNumber(item.count) ?? 0 }))
}

function parseJobPage(value: unknown): JobPage {
  if (!isRecord(value) || !Array.isArray(value.items)) throw malformed('expected a job list.')
  const facets = isRecord(value.facets) ? value.facets : {}
  return {
    items: value.items.map(parseJob),
    total: optionalNumber(value.total) ?? 0,
    page: optionalNumber(value.page) ?? 1,
    pageSize: optionalNumber(value.page_size) ?? 25,
    totalPages: optionalNumber(value.total_pages) ?? 1,
    facets: {
      statuses: parseFacetList(facets.statuses),
      customerIds: parseFacetList(facets.customer_ids),
      documentTypes: parseFacetList(facets.document_types),
    },
  }
}

function parseOptions(value: unknown): UploadOptions {
  if (!isRecord(value)) throw malformed('expected upload options.')
  const loans = Array.isArray(value.loans) ? value.loans.filter(isRecord) : []

  return {
    allowedExtensions: Array.isArray(value.allowed_extensions) ? value.allowed_extensions.map(String) : [],
    maxUploadBytes: optionalNumber(value.max_upload_bytes) ?? 0,
    customers: Array.isArray(value.customers) ? value.customers.map(String) : [],
    loans: loans.map((loan) => ({ loanId: String(loan.loan_id), customerId: String(loan.customer_id) })),
  }
}

// ------------------------------------------------------------
// Endpoints
// ------------------------------------------------------------

export async function getUploadOptions(signal?: AbortSignal): Promise<UploadOptions> {
  return parseOptions(await getJson('/api/documents/upload-options', signal))
}

export async function listJobs(query: JobQuery, signal?: AbortSignal): Promise<JobPage> {
  const params = new URLSearchParams({ page: String(query.page), page_size: String(query.pageSize) })
  if (query.status) params.set('status', query.status)
  if (query.customerId) params.set('customer_id', query.customerId)
  if (query.documentType) params.set('document_type', query.documentType)
  return parseJobPage(await getJson(`/api/jobs?${params}`, signal))
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<IngestionJob> {
  return parseJob(await getJson(`/api/jobs/${encodeURIComponent(jobId)}`, signal))
}

export async function retryJob(jobId: string, signal?: AbortSignal): Promise<IngestionJob> {
  return parseJob(await postJson(`/api/jobs/${encodeURIComponent(jobId)}/retry`, signal))
}

/**
 * Upload with XMLHttpRequest, because fetch cannot report upload progress.
 * Resolves once the server has stored the file and queued processing.
 */
export function uploadDocument(
  file: File,
  customerId: string,
  loanId: string | null,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    form.append('customer_id', customerId)
    if (loanId) form.append('loan_id', loanId)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE_URL}/api/documents/upload`)
    xhr.responseType = 'json'

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }

    xhr.onload = () => {
      const body: unknown = xhr.response
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          if (!isRecord(body)) throw malformed('expected an upload result.')
          resolve({ job: parseJob(body.job), duplicate: body.duplicate === true })
        } catch (error) {
          reject(error)
        }
        return
      }
      const detail = isRecord(body) && typeof body.detail === 'string' ? body.detail : null
      reject(new ApiError('http', detail ?? `The upload failed (HTTP ${xhr.status}).`, xhr.status))
    }

    xhr.onerror = () => reject(new ApiError('network', 'The backend could not be reached.'))
    xhr.onabort = () => reject(new ApiError('aborted', 'The upload was cancelled.'))

    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}
