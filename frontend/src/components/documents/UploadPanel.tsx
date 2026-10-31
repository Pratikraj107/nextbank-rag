import {
  CircleAlert,
  CloudUpload,
  FileUp,
  RotateCw,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'

import type { UploadState } from '../../hooks/useUpload'
import { describeLoadError } from '../../hooks/useDocuments'
import { getUploadOptions, type UploadOptions } from '../../lib/uploads'
import { JobStatusBadge } from '../activity/JobStatusBadge'
import { StageList } from '../activity/StageList'
import { humanize } from '../../lib/sources'
import { FileTypeIcon } from '../FileTypeIcon'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

interface UploadPanelProps {
  upload: UploadState
  busy: boolean
  onStart: (file: File, customerId: string, loanId: string | null) => void
  onRetry: () => void
  onResume: () => void
  onReset: () => void
  onOpenDocument: (documentId: string) => void
  onClose: () => void
}

export function UploadPanel({
  upload,
  busy,
  onStart,
  onRetry,
  onResume,
  onReset,
  onOpenDocument,
  onClose,
}: UploadPanelProps) {
  const [options, setOptions] = useState<UploadOptions | null>(null)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [customerId, setCustomerId] = useState('')
  const [loanId, setLoanId] = useState('')
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    getUploadOptions(controller.signal)
      .then(setOptions)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setOptionsError(describeLoadError(error))
      })
    return () => controller.abort()
  }, [])

  const loans = options?.loans.filter((loan) => loan.customerId === customerId) ?? []
  const showForm = upload.phase === 'idle'

  const chooseFile = (candidate: File | null) => {
    setFileError(null)
    setFile(null)
    if (!candidate || !options) return
    if (!options.allowedExtensions.includes(extensionOf(candidate.name))) {
      setFileError(`Unsupported file type. Use ${options.allowedExtensions.join(', ')}.`)
    } else if (candidate.size === 0) {
      setFileError('The file is empty.')
    } else if (candidate.size > options.maxUploadBytes) {
      setFileError(`The file is larger than the ${formatBytes(options.maxUploadBytes)} limit.`)
    } else {
      setFile(candidate)
    }
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    if (!busy) chooseFile(event.dataTransfer.files[0] ?? null)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (file && customerId && !busy) onStart(file, customerId, loanId || null)
  }

  const startOver = () => {
    onReset()
    setFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const job = upload.job

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-ink">Upload document</h2>
          <p className="mt-0.5 text-xs text-muted">
            Add a synthetic customer or loan document. It becomes searchable once processing finishes.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="-mr-1.5 rounded-lg p-1.5 text-muted hover:bg-canvas hover:text-ink"
          aria-label="Close upload panel"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {optionsError && (
          <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
            {optionsError}
          </p>
        )}

        {showForm ? (
          <form onSubmit={submit} className="space-y-5">
            <div>
              <label
                htmlFor="upload-file"
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
                  dragging ? 'border-accent bg-accent-soft' : 'border-line-strong bg-canvas/50 hover:bg-canvas'
                }`}
              >
                <CloudUpload className="h-7 w-7 text-accent" aria-hidden />
                <span className="text-sm font-medium text-ink">Drop a file here, or click to choose</span>
                <span className="text-xs text-muted">
                  {options
                    ? `${options.allowedExtensions.join(', ')} · up to ${formatBytes(options.maxUploadBytes)}`
                    : 'Loading accepted formats…'}
                </span>
              </label>
              <input
                ref={inputRef}
                id="upload-file"
                type="file"
                accept={options?.allowedExtensions.join(',')}
                disabled={!options}
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                className="sr-only"
              />
              {fileError && (
                <p role="alert" className="mt-2 text-sm text-red-700">{fileError}</p>
              )}
              {file && (
                <div className="mt-3 flex items-center gap-3 rounded-lg border border-line px-3 py-2">
                  <FileTypeIcon filename={file.name} className="h-4 w-4 text-ink-soft" />
                  <span className="min-w-0 flex-1 truncate text-sm text-ink" title={file.name}>{file.name}</span>
                  <span className="text-xs text-muted tabular-nums">{formatBytes(file.size)}</span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="upload-customer" className="mb-1 block text-xs font-medium text-muted">
                  Customer ID <span className="text-red-700">*</span>
                </label>
                <select
                  id="upload-customer"
                  required
                  value={customerId}
                  onChange={(event) => {
                    setCustomerId(event.target.value)
                    setLoanId('')
                  }}
                  className="h-9 w-full rounded-lg border border-line-strong bg-white px-2.5 text-sm text-ink focus:border-accent/50 focus:ring-4 focus:ring-accent/10 focus:outline-none"
                >
                  <option value="">Select customer</option>
                  {options?.customers.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="upload-loan" className="mb-1 block text-xs font-medium text-muted">
                  Loan ID (optional)
                </label>
                <select
                  id="upload-loan"
                  value={loanId}
                  disabled={!customerId}
                  onChange={(event) => setLoanId(event.target.value)}
                  className="h-9 w-full rounded-lg border border-line-strong bg-white px-2.5 text-sm text-ink focus:border-accent/50 focus:ring-4 focus:ring-accent/10 focus:outline-none disabled:bg-canvas"
                >
                  <option value="">No loan</option>
                  {loans.map((loan) => <option key={loan.loanId} value={loan.loanId}>{loan.loanId}</option>)}
                </select>
              </div>
            </div>
            <p className="text-xs text-muted">
              Customers and loans come from the enterprise records. Identifiers found in the document
              must match these, or processing fails.
            </p>

            {upload.error && (
              <p role="alert" className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {upload.error}
              </p>
            )}

            <button
              type="submit"
              disabled={!file || !customerId || busy}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
            >
              <FileUp className="h-4 w-4" aria-hidden />
              Upload and process
            </button>
          </form>
        ) : (
          <div className="space-y-5" aria-live="polite">
            <div className="flex items-center gap-3 rounded-lg border border-line px-3 py-2.5">
              <FileTypeIcon filename={job?.filename ?? upload.filename ?? ''} className="h-4 w-4 text-ink-soft" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
                {job?.filename ?? upload.filename}
              </span>
              {job && <JobStatusBadge status={job.status} />}
            </div>

            {upload.phase === 'uploading' && (
              <div>
                <div className="mb-1 flex justify-between text-xs text-muted">
                  <span>Uploading</span>
                  <span className="tabular-nums">{Math.round(upload.progress * 100)}%</span>
                </div>
                <div
                  role="progressbar"
                  aria-label="Upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(upload.progress * 100)}
                  className="h-1.5 overflow-hidden rounded-full bg-canvas"
                >
                  <div className="h-full bg-accent transition-[width]" style={{ width: `${upload.progress * 100}%` }} />
                </div>
              </div>
            )}

            {upload.duplicate && job && (
              <p className="rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink-soft">
                This file was already uploaded for {job.customerId}
                {job.loanId ? ` and ${job.loanId}` : ''}. Showing the existing job instead of processing it again.
              </p>
            )}

            {job && job.stages.length > 0 && <StageList stages={job.stages} />}

            {job?.status === 'failed' && job.error && (
              <p role="alert" className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {job.error}
              </p>
            )}

            {upload.error && (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                <p>{upload.error}</p>
                {job && !['ready', 'failed'].includes(job.status) && (
                  <button type="button" onClick={onResume} className="mt-1 font-medium underline">
                    Check again
                  </button>
                )}
              </div>
            )}

            {job?.status === 'ready' && (
              <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 text-sm text-emerald-900">
                <p>
                  Ready and searchable: {job.chunkCount ?? 0} chunk{job.chunkCount === 1 ? '' : 's'}
                  {job.documentType ? `, classified as ${humanize(job.documentType)}` : ''}.
                </p>
                {job.warnings.length > 0 && (
                  <ul className="list-disc pl-5 text-xs text-emerald-900/80">
                    {job.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                  </ul>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {job?.status === 'ready' && (
                <button
                  type="button"
                  onClick={() => onOpenDocument(job.documentId)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
                >
                  Open document
                </button>
              )}
              {job?.status === 'failed' && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas"
                >
                  <RotateCw className="h-3.5 w-3.5" aria-hidden />
                  Retry processing
                </button>
              )}
              {!busy && (
                <button
                  type="button"
                  onClick={startOver}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas"
                >
                  Upload another file
                </button>
              )}
            </div>

            {busy && (
              <p className="text-xs text-muted">
                You can close this panel; processing continues and the status stays visible in the header.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
