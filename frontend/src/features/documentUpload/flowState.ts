import { documentIdOf, withoutQuery } from '../../api/documents.ts'
import type { ExtractionEvent, ValidationEvent } from '../../api/documentStreams.ts'
import { ApiError } from '../../api/httpClient.ts'
import type { DocumentRef, Project } from '../../api/projects.ts'
import type { DocumentExtraction, ExtractionState, LocalUpload, ProjectFlowState, RunStatus } from './projectFlowContext.ts'
import { selectHasValidDocument, selectIsLinked } from './selectors.ts'

// The state changes of ProjectFlowProvider, as plain functions for `setState((prev) => …)`: each takes the previous
// state and returns the next one, without side effects.

export const UPLOAD_FAILED = 'Hochladen fehlgeschlagen.'
export const NOT_LINKED = 'Das Dokument wurde nicht übernommen.'
export const REMOVE_FAILED = 'Das Dokument konnte nicht entfernt werden. Bitte versuchen Sie es erneut.'
export const ADVANCE_REMOVE_FAILED =
  'Nicht verwendbare Dokumente konnten nicht entfernt werden. Bitte versuchen Sie es erneut.'
export const NO_VALID_DOCUMENT = 'Keines der Dokumente ist verwendbar. Bitte fügen Sie einen Finanzbericht hinzu.'
export const PROJECT_NOT_FOUND = 'Das Projekt wurde nicht gefunden.'
export const PROJECT_LOAD_FAILED = 'Das Projekt konnte nicht geladen werden.'
export const CHECK_INTERRUPTED = 'Die Prüfung wurde unterbrochen.'
export const EXTRACTION_FAILED = 'Die Extraktion ist fehlgeschlagen.'
export const EXTRACTION_INTERRUPTED = 'Die Extraktion wurde unterbrochen.'

const IDLE_EXTRACTION: ExtractionState = {
  status: 'idle',
  error: null,
  overallProgress: 0,
  positions: 0,
  documents: {},
  found: [],
}

/** The state before the project has loaded. */
export const INITIAL_FLOW_STATE: ProjectFlowState = {
  project: null,
  loadError: null,
  uploads: {},
  removing: [],
  sheetKeys: {},
  validation: { run: 0, status: 'idle', error: null, documents: {} },
  extraction: IDLE_EXTRACTION,
  step: 'upload',
  advancing: false,
  message: null,
}

function withValidationRun(prev: ProjectFlowState): ProjectFlowState['validation'] {
  return { ...prev.validation, run: prev.validation.run + 1, status: 'running', error: null }
}

/** The loaded project; with documents, their validation starts. */
export function withProject(prev: ProjectFlowState, project: Project): ProjectFlowState {
  return {
    ...prev,
    project,
    loadError: null,
    validation: project.documents.length > 0 ? withValidationRun(prev) : prev.validation,
  }
}

export function withLoadError(prev: ProjectFlowState, loadError: string): ProjectFlowState {
  return { ...prev, loadError }
}

/** New files of this session and the message about the rejected ones (`null` clears the message). */
export function withAddedUploads(prev: ProjectFlowState, added: readonly LocalUpload[], message: string | null): ProjectFlowState {
  const uploads = { ...prev.uploads }
  for (const upload of added) {
    uploads[upload.localKey] = upload
  }
  return { ...prev, uploads, message }
}

/** Changes one upload; nothing when it was removed meanwhile. */
export function withUploadChange(prev: ProjectFlowState, localKey: string, change: Partial<LocalUpload>): ProjectFlowState {
  const upload = prev.uploads[localKey]
  if (!upload) {
    return prev
  }
  return { ...prev, uploads: { ...prev.uploads, [localKey]: { ...upload, ...change } } }
}

export function withoutUpload(prev: ProjectFlowState, localKey: string): ProjectFlowState {
  if (!Object.hasOwn(prev.uploads, localKey)) {
    return prev
  }
  const uploads = { ...prev.uploads }
  delete uploads[localKey]
  return { ...prev, uploads }
}

/**
 * The finished uploads that one PATCH links, once no upload runs any more; empty while one runs. Failed uploads
 * never count (AC-16).
 */
export function uploadsToLink(state: ProjectFlowState): LocalUpload[] {
  const uploads = Object.values(state.uploads)
  if (uploads.some((upload) => upload.ref === null && upload.error === null)) {
    return []
  }
  return uploads.filter((upload) => upload.ref !== null && upload.error === null)
}

/** The PATCH body's documents and, at the same index, the local key of the upload each one came from. */
export type LinkRequest = {
  documents: DocumentRef[]
  owners: Array<string | null>
}

/**
 * All of the project's documents plus the new ones (AC-4), each once and without a query: the backend rejects URLs
 * that still carry the upload signature.
 */
export function linkRequest(project: Project, uploads: readonly LocalUpload[]): LinkRequest {
  const documents: DocumentRef[] = []
  const owners: Array<string | null> = []
  const urls = new Set<string>()
  const add = (ref: DocumentRef, owner: string | null) => {
    const url = withoutQuery(ref.url)
    if (!urls.has(url)) {
      urls.add(url)
      documents.push({ url, name: ref.name, size: ref.size, contentType: ref.contentType })
      owners.push(owner)
    }
  }
  project.documents.forEach((ref) => add(ref, null))
  uploads.forEach((upload) => upload.ref && add(upload.ref, upload.localKey))
  return { documents, owners }
}

/**
 * The documentId each linked upload ended up as: its own URL, or, when the backend found the same file already
 * stored and linked that document instead, the document with the same name and size. `null` when neither is there.
 */
export function matchLinked(uploads: readonly LocalUpload[], project: Project): Map<string, string | null> {
  const matches = new Map<string, string | null>()
  for (const upload of uploads) {
    const ref = upload.ref
    if (!ref) {
      continue
    }
    const url = withoutQuery(ref.url)
    const match =
      project.documents.find((document) => withoutQuery(document.url) === url) ??
      project.documents.find((document) => document.name === ref.name && document.size === ref.size)
    matches.set(upload.localKey, match ? documentIdOf(match.url) : null)
  }
  return matches
}

/**
 * The documents a PATCH linked only for uploads the user removed while it ran, which are therefore unlinked again.
 * A document the project had before the PATCH (`linkedBefore`) is never one of them, and neither is a document that
 * an upload the user kept ended up as too (the same file added twice): the user still wants those.
 */
export function discardedDocuments(
  matches: ReadonlyMap<string, string | null>,
  discarded: ReadonlySet<string>,
  linkedBefore: ReadonlySet<string>,
): string[] {
  const removed = new Set<string>()
  const kept = new Set<string>()
  for (const [localKey, documentId] of matches) {
    if (documentId === null) {
      continue
    }
    if (discarded.has(localKey)) {
      removed.add(documentId)
    } else {
      kept.add(documentId)
    }
  }
  return [...removed].filter((documentId) => !kept.has(documentId) && !linkedBefore.has(documentId))
}

/** The project after a PATCH: linked uploads leave the session's files, and a new validation run starts (AC-7). */
export function withLinked(prev: ProjectFlowState, project: Project, matches: ReadonlyMap<string, string | null>): ProjectFlowState {
  const uploads = { ...prev.uploads }
  const sheetKeys = { ...prev.sheetKeys }
  for (const [localKey, documentId] of matches) {
    const upload = uploads[localKey]
    if (!upload) {
      continue
    }
    if (documentId === null) {
      uploads[localKey] = { ...upload, ref: null, error: NOT_LINKED }
      continue
    }
    delete uploads[localKey]
    const hadSheet = selectIsLinked(prev, documentId) || Object.hasOwn(sheetKeys, documentId)
    if (!hadSheet) {
      sheetKeys[documentId] = localKey
    }
  }
  return { ...prev, project, uploads, sheetKeys, validation: withValidationRun(prev) }
}

/**
 * The uploads a failed PATCH rejected, from the ValidationProblem's `documents[i]…` fields; `null` when the failure
 * cannot be put down to single uploads.
 */
export function uploadsRejectedBy(error: unknown, owners: ReadonlyArray<string | null>): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 400) {
    return null
  }
  const fields = Object.keys(error.errors)
  const rejected = new Set<string>()
  for (const field of fields) {
    const index = /^documents\[(\d+)\]/i.exec(field)?.[1]
    const owner = index === undefined ? null : owners[Number(index)]
    if (!owner) {
      return null
    }
    rejected.add(owner)
  }
  return rejected.size > 0 ? [...rejected] : null
}

/**
 * Uploads a PATCH did not link; they are never sent again. Always a new state, even when none of them is left (the
 * user removed them meanwhile): the provider then looks for uploads to link again, so the uploads of that PATCH it
 * did not reject go with the next one instead of waiting for an unrelated change.
 */
export function withLinkFailure(prev: ProjectFlowState, localKeys: readonly string[]): ProjectFlowState {
  let next: ProjectFlowState = { ...prev }
  for (const localKey of localKeys) {
    next = withUploadChange(next, localKey, { ref: null, error: NOT_LINKED })
  }
  return next
}

export function withRemoving(prev: ProjectFlowState, documentId: string): ProjectFlowState {
  return prev.removing.includes(documentId) ? prev : { ...prev, removing: [...prev.removing, documentId] }
}

/** A document the backend no longer links to the project. */
export function withUnlinked(prev: ProjectFlowState, documentId: string): ProjectFlowState {
  const project = prev.project && {
    ...prev.project,
    documents: prev.project.documents.filter((ref) => documentIdOf(ref.url) !== documentId),
  }
  return { ...prev, project, removing: prev.removing.filter((id) => id !== documentId) }
}

export function withUnlinkFailure(prev: ProjectFlowState, documentId: string): ProjectFlowState {
  return { ...prev, removing: prev.removing.filter((id) => id !== documentId), message: REMOVE_FAILED }
}

export function withAdvancing(prev: ProjectFlowState): ProjectFlowState {
  return { ...prev, advancing: true, message: null }
}

/**
 * How `advance` ends once the invalid documents are removed: step `extract` with a fresh extraction run when a valid
 * document remains, otherwise a message and step `upload` (AC-25).
 */
export function withAdvanceOutcome(prev: ProjectFlowState, removedAll: boolean): ProjectFlowState {
  if (!removedAll) {
    return { ...prev, advancing: false, message: ADVANCE_REMOVE_FAILED }
  }
  if (!selectHasValidDocument(prev)) {
    return { ...prev, advancing: false, message: NO_VALID_DOCUMENT }
  }
  return { ...prev, advancing: false, step: 'extract', extraction: { ...IDLE_EXTRACTION, status: 'running' } }
}

/** One event of validation run `run`; events of older runs and of documents not linked are ignored. */
export function withValidationEvent(prev: ProjectFlowState, run: number, event: ValidationEvent): ProjectFlowState {
  const validation = prev.validation
  if (validation.run !== run || validation.status !== 'running') {
    return prev
  }
  let status: RunStatus = validation.status
  let { error, documents } = validation
  if (event.document === '') {
    if (event.error !== undefined) {
      status = 'failed'
      error = event.error
    }
  } else if (selectIsLinked(prev, event.document)) {
    const before = documents[event.document]
    documents = {
      ...documents,
      [event.document]: { progress: event.documentProgress ?? before?.progress ?? 0, error: event.error ?? null },
    }
  }
  if (event.overallProgress >= 100 && status === 'running') {
    status = 'done'
  }
  return { ...prev, validation: { ...validation, status, error, documents } }
}

/** The end of validation run `run`: a stream that ends before its last event, or fails, fails the run. */
export function withValidationEnd(prev: ProjectFlowState, run: number, failure: string | null): ProjectFlowState {
  const validation = prev.validation
  if (validation.run !== run || validation.status !== 'running') {
    return prev
  }
  return { ...prev, validation: { ...validation, status: 'failed', error: failure ?? CHECK_INTERRUPTED } }
}

const NOT_STARTED: DocumentExtraction = { pages: null, pagesRead: 0, progress: 0, error: null }

/** One event of the extraction run; events of documents not linked are ignored. */
export function withExtractionEvent(prev: ProjectFlowState, event: ExtractionEvent): ProjectFlowState {
  const extraction = prev.extraction
  if (extraction.status !== 'running') {
    return prev
  }
  let status: RunStatus = extraction.status
  let { error, documents, found } = extraction
  if (event.document === '') {
    if (event.error !== undefined) {
      status = 'failed'
      error = event.error
    }
  } else if (selectIsLinked(prev, event.document)) {
    const before = documents[event.document] ?? NOT_STARTED
    documents = {
      ...documents,
      [event.document]: {
        pages: event.pages ?? before.pages,
        pagesRead: event.pagesRead ?? before.pagesRead,
        progress: event.documentProgress ?? before.progress,
        error: event.error ?? before.error,
      },
    }
    if (event.position) {
      found = [...found, { ...event.position, documentId: event.document }]
    }
  }
  if (event.overallProgress >= 100 && status === 'running') {
    status = 'done'
  }
  return {
    ...prev,
    extraction: {
      status,
      error,
      overallProgress: event.overallProgress,
      positions: event.positions ?? extraction.positions,
      documents,
      found,
    },
  }
}

/** The end of the extraction stream: ending before its last event, or failing, fails the run. */
export function withExtractionEnd(prev: ProjectFlowState, failure: string | null): ProjectFlowState {
  if (prev.extraction.status !== 'running') {
    return prev
  }
  return { ...prev, extraction: { ...prev.extraction, status: 'failed', error: failure ?? EXTRACTION_INTERRUPTED } }
}
