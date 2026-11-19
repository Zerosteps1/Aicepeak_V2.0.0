import { documentIdOf } from '../../api/documents.ts'
import type { DocumentRef } from '../../api/projects.ts'
import { extensionOf } from './files.ts'
import type { FoundPosition, LocalUpload, ProjectFlowState, RunStatus, ValidationState } from './projectFlowContext.ts'

// Everything derived from the flow's state. Pure functions: nothing derived is stored.

/** Above this many pages an extraction line is one continuous strip instead of one segment per page. */
export const STRIP_ABOVE_PAGES = 150

/** Rows of the latest-positions table. */
export const LATEST_POSITIONS = 3

/** Shown for a document whose check did not finish. */
export const CHECK_FAILED = 'Die Prüfung ist fehlgeschlagen.'

/**
 * Status of one document sheet: `uploading` to the storage, `queued` uploaded and waiting to be checked, `checking`
 * by the backend, `valid` or `invalid` as checked, `failed` when the upload, the linking or the check failed.
 */
export type SheetStatus = 'uploading' | 'queued' | 'checking' | 'valid' | 'invalid' | 'failed'

/** One document sheet in the drop tray. */
export type Sheet = {
  /** Stable React key: the upload's local key, kept after linking, or the documentId of an earlier document. */
  key: string
  /** What `removeDocument` takes: the documentId once linked, otherwise the local key. */
  id: string
  /** `null` while the file is not linked to the project. */
  documentId: string | null
  name: string
  /** Bytes. */
  size: number
  /** Upper-case extension, e.g. `PDF`. */
  kind: string
  status: SheetStatus
  /** Upload progress while `uploading`, check progress while `checking`; 0–100. */
  progress: number
  /** Why the sheet is `invalid` or `failed`, ready to show; `null` otherwise. */
  error: string | null
}

function isLinked(state: ProjectFlowState, documentId: string): boolean {
  return state.project?.documents.some((ref) => documentIdOf(ref.url) === documentId) ?? false
}

function checkOf(validation: ValidationState, documentId: string): Pick<Sheet, 'status' | 'progress' | 'error'> {
  const check = validation.documents[documentId]
  if (check?.error != null) {
    return { status: 'invalid', progress: 100, error: check.error }
  }
  if (check && check.progress >= 100) {
    return { status: 'valid', progress: 100, error: null }
  }
  if (validation.status === 'failed' || validation.status === 'done') {
    return { status: 'failed', progress: check?.progress ?? 0, error: validation.error ?? CHECK_FAILED }
  }
  if (check) {
    return { status: 'checking', progress: check.progress, error: null }
  }
  return { status: 'queued', progress: 0, error: null }
}

function linkedSheet(state: ProjectFlowState, ref: DocumentRef): Sheet {
  const documentId = documentIdOf(ref.url)
  return {
    key: state.sheetKeys[documentId] ?? documentId,
    id: documentId,
    documentId,
    name: ref.name,
    size: ref.size,
    kind: extensionOf(ref.name).toUpperCase(),
    ...checkOf(state.validation, documentId),
  }
}

function localSheet(upload: LocalUpload): Sheet {
  const { localKey, file, progress, ref, error } = upload
  const common = { key: localKey, id: localKey, documentId: null, name: file.name, size: file.size, kind: extensionOf(file.name).toUpperCase() }
  if (error !== null) {
    return { ...common, status: 'failed', progress, error }
  }
  if (ref !== null) {
    return { ...common, status: 'queued', progress: 100, error: null }
  }
  return { ...common, status: 'uploading', progress, error: null }
}

/** The sheets of the drop tray: the project's documents (without those being removed), then this session's files. */
export function selectSheets(state: ProjectFlowState): Sheet[] {
  const linked = (state.project?.documents ?? [])
    .filter((ref) => !state.removing.includes(documentIdOf(ref.url)))
    .map((ref) => linkedSheet(state, ref))
  return [...linked, ...Object.values(state.uploads).map(localSheet)]
}

/** Whether a sheet has its final result. A linked document whose check failed has none: it must be removed first. */
function isSettled(sheet: Sheet): boolean {
  return sheet.status === 'valid' || sheet.status === 'invalid' || (sheet.status === 'failed' && sheet.documentId === null)
}

/**
 * Whether "Weiter zur Extraktion" is available (AC-23): in step `upload`, with the project loaded, at least one sheet,
 * every upload finished and linked, every linked document checked, and no removal or `advance` running.
 */
export function selectCanAdvance(state: ProjectFlowState): boolean {
  if (state.step !== 'upload' || state.advancing || state.project === null || state.removing.length > 0) {
    return false
  }
  const sheets = selectSheets(state)
  return sheets.length > 0 && sheets.every(isSettled)
}

/** Whether a valid document is linked; what `advance` needs after removing the invalid ones (AC-25). */
export function selectHasValidDocument(state: ProjectFlowState): boolean {
  return selectSheets(state).some((sheet) => sheet.status === 'valid')
}

/** The documentIds of the invalid linked documents, which `advance` removes (AC-24). */
export function selectInvalidDocumentIds(state: ProjectFlowState): string[] {
  return selectSheets(state).flatMap((sheet) => (sheet.status === 'invalid' && sheet.documentId !== null ? [sheet.documentId] : []))
}

/** `4,1 MB`: bytes in MiB with one decimal, as the design shows sizes. */
export function formatMegabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`
}

function documentsLabel(count: number): string {
  return `${count.toLocaleString('de-DE')} ${count === 1 ? 'Dokument' : 'Dokumente'}`
}

/** Totals of the drop tray. */
export type UploadTotals = {
  documents: number
  bytes: number
  /** E.g. `2 Dokumente · 5,3 MB`, or `Noch keine Dokumente`. */
  label: string
}

export function selectUploadTotals(state: ProjectFlowState): UploadTotals {
  const sheets = selectSheets(state)
  const bytes = sheets.reduce((sum, sheet) => sum + sheet.size, 0)
  const label = sheets.length === 0 ? 'Noch keine Dokumente' : `${documentsLabel(sheets.length)} · ${formatMegabytes(bytes)}`
  return { documents: sheets.length, bytes, label }
}

/** The hint next to "Weiter zur Extraktion": the current message, otherwise how far the documents are. */
export function selectUploadHint(state: ProjectFlowState): string {
  if (state.message !== null) {
    return state.message
  }
  if (state.project === null) {
    return state.loadError ?? 'Das Projekt wird geladen …'
  }
  const sheets = selectSheets(state)
  if (sheets.length === 0) {
    return 'Weiter, sobald alle Dokumente geprüft sind.'
  }
  if (sheets.some((sheet) => sheet.status === 'uploading')) {
    return 'Dokumente werden hochgeladen …'
  }
  if (sheets.some((sheet) => sheet.status === 'queued' || sheet.status === 'checking')) {
    return 'Dokumente werden geprüft …'
  }
  if (sheets.some((sheet) => !isSettled(sheet))) {
    return 'Die Prüfung ist fehlgeschlagen. Bitte entfernen Sie die betroffenen Dokumente.'
  }
  const valid = sheets.filter((sheet) => sheet.status === 'valid').length
  if (valid === 0) {
    return 'Keines der Dokumente enthält einen Finanzbericht.'
  }
  if (valid < sheets.length) {
    return `${valid.toLocaleString('de-DE')} von ${sheets.length.toLocaleString('de-DE')} Dokumenten werden verwendet.`
  }
  return 'Alle Dokumente geprüft.'
}

/** State of one page segment of an extraction line. */
export type SegmentState = 'done' | 'now' | 'todo'

/** One segment per page, or for long documents one strip filled to `read` (0–1). */
export type ExtractionTrack = { kind: 'segments'; segments: SegmentState[] } | { kind: 'strip'; read: number }

/** One line per valid document in step `extract`. */
export type ExtractionLine = {
  documentId: string
  name: string
  /** Upper-case extension, e.g. `PDF`. */
  kind: string
  /** `null` until the backend has said. */
  pages: number | null
  pagesRead: number
  /** Whether the backend is reading this document right now. */
  reading: boolean
  /** Why reading this document failed, as the backend says. */
  error: string | null
  track: ExtractionTrack
}

function trackOf(pages: number | null, pagesRead: number, reading: boolean): ExtractionTrack {
  if (pages === null) {
    return { kind: 'segments', segments: [] }
  }
  if (pages > STRIP_ABOVE_PAGES) {
    return { kind: 'strip', read: pages > 0 ? pagesRead / pages : 0 }
  }
  const segments = Array.from({ length: pages }, (_, index): SegmentState => {
    if (index < pagesRead) {
      return 'done'
    }
    return index === pagesRead && reading ? 'now' : 'todo'
  })
  return { kind: 'segments', segments }
}

export function selectExtractionLines(state: ProjectFlowState): ExtractionLine[] {
  const { extraction } = state
  return selectSheets(state).flatMap((sheet) => {
    if (sheet.status !== 'valid' || sheet.documentId === null) {
      return []
    }
    const progress = extraction.documents[sheet.documentId]
    const pages = progress?.pages ?? null
    const pagesRead = Math.min(progress?.pagesRead ?? 0, pages ?? Number.POSITIVE_INFINITY)
    const error = progress?.error ?? null
    const reading = extraction.status === 'running' && progress !== undefined && error === null && (pages === null || pagesRead < pages)
    return [{ documentId: sheet.documentId, name: sheet.name, kind: sheet.kind, pages, pagesRead, reading, error, track: trackOf(pages, pagesRead, reading) }]
  })
}

/** Totals and hint of the extraction panel. */
export type ExtractionSummary = {
  status: RunStatus
  documents: number
  pages: number
  pagesRead: number
  positions: number
  /** E.g. `3 Dokumente · 53 Seiten`. */
  label: string
  hint: string
  /** Whether "Weiter zu den Positionen" is available: all pages read. */
  canContinue: boolean
}

export function selectExtractionSummary(state: ProjectFlowState): ExtractionSummary {
  const lines = selectExtractionLines(state)
  const pages = lines.reduce((sum, line) => sum + (line.pages ?? 0), 0)
  const pagesRead = lines.reduce((sum, line) => sum + line.pagesRead, 0)
  const { status, positions } = state.extraction
  const hint =
    status === 'failed'
      ? 'Die Extraktion ist abgebrochen. Bitte versuchen Sie es erneut.'
      : status === 'done'
        ? 'Alle Seiten gelesen.'
        : 'Verfügbar, sobald alle Seiten gelesen sind.'
  return {
    status,
    documents: lines.length,
    pages,
    pagesRead,
    positions,
    label: `${documentsLabel(lines.length)} · ${pages.toLocaleString('de-DE')} Seiten`,
    hint,
    canContinue: status === 'done',
  }
}

/** The latest positions found, newest first; at most `LATEST_POSITIONS`. */
export function selectLatestPositions(state: ProjectFlowState): FoundPosition[] {
  return state.extraction.found.slice(-LATEST_POSITIONS).reverse()
}

/** Whether the documentId is one of the project's documents. */
export function selectIsLinked(state: ProjectFlowState, documentId: string): boolean {
  return isLinked(state, documentId)
}
