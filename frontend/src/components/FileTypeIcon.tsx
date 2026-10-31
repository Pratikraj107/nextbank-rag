import { File, FileSpreadsheet, FileText, FileType2, Globe, Mail } from 'lucide-react'

/** Icon for a document, from its source format or file extension. */
export function FileTypeIcon({ filename, sourceType, className = 'h-4 w-4' }: {
  filename: string
  sourceType?: string | null
  className?: string
}) {
  const kind = (sourceType || filename.split('.').at(-1) || '').toLowerCase()

  switch (kind) {
    case 'csv':
      return <FileSpreadsheet className={className} aria-hidden />
    case 'eml':
      return <Mail className={className} aria-hidden />
    case 'html':
    case 'htm':
      return <Globe className={className} aria-hidden />
    case 'docx':
      return <FileType2 className={className} aria-hidden />
    case 'pdf':
      return <FileText className={className} aria-hidden />
    default:
      return <File className={className} aria-hidden />
  }
}
