import { createContext } from 'react'
import type { ExtractedPosition } from '../../api/documentStreams.ts'
import type { DocumentRef, Project } from '../../api/projects.ts'

/** The two steps of a new project: add and check documents, then extract positions. */
export type FlowStep = 'upload' | 'extract'

/** How a backend stream run stands. */
export type RunStatus = 'idle' | 'running' | 'done' | 'failed'

/** A file of this session that is not linked to the project yet. */
export type LocalUpload = {
  /** Key of this file in the session; starts with `upload:`, so it never looks like a documentId. */
  localKey: string
  file: File
  /** Upload progress in percent (0–100). */
  progress: number
  /** The finished upload, linked with the next PATCH; `null` while it runs or after it failed. */
  ref: DocumentRef | null
  /** Why the upload or its linking failed, ready to show; `null` otherwise. Failed uploads are never linked. */
  error: string | null
}

/** What the validation stream reported for one document. */
export type DocumentCheck = {
  /** 0–100. */
  progress: number
  /** Why the document is invalid, as the backend says; `null` while it is not. */
  error: string | null
}

/** The validation of the project's documents. Documents never change, so results are kept across runs. */
export type ValidationState = {
  /**
   * Counts the runs: the first starts once a loaded project has documents, then every PATCH starts one (AC-7), and so
   * does `retryValidation`.
   */
  run: number
  status: RunStatus
  /** Why the current run failed as a whole, ready to show. */
  error: string | null
  /** By documentId. */
  documents: Readonly<Record<string, DocumentCheck>>
}

/** What the extraction stream reported for one document. */
export type DocumentExtraction = {
  /** `null` until the backend has said. */
  pages: number | null
  pagesRead: number
  /** 0–100. */
  progress: number
  error: string | null
}

/** An extracted position with the document it was found in. */
export type FoundPosition = ExtractedPosition & { documentId: string }

/** The extraction of the project's documents (step `extract`). */
export type ExtractionState = {
  /** Counts the runs: `advance` starts the first, `retryExtraction` each further one; `0` before step `extract`. */
  run: number
  status: RunStatus
  /** Why the run failed as a whole, as the backend says. */
  error: string | null
  /** 0–100. */
  overallProgress: number
  /** Positions found in the whole project so far, as the backend counts them. */
  positions: number
  /** By documentId. */
  documents: Readonly<Record<string, DocumentExtraction>>
  /** Every position the stream reported, oldest first. */
  found: readonly FoundPosition[]
}

/**
 * Everything the "Neues Projekt" flow knows, held once by `ProjectFlowProvider`. Nothing in it is derived from the
 * rest: sheets, statuses, totals and hints come from the functions in `selectors.ts`.
 */
export type ProjectFlowState = {
  /** The project as the backend last returned it; `null` until loaded. */
  project: Project | null
  /** Why the project could not be loaded, ready to show. */
  loadError: string | null
  /** Files of this session not linked yet, by local key, in the order they were added. */
  uploads: Readonly<Record<string, LocalUpload>>
  /** documentIds whose DELETE waits or runs; their sheets are hidden. */
  removing: readonly string[]
  /** documentId → local key of the upload it came from, so its sheet keeps its React key after linking. */
  sheetKeys: Readonly<Record<string, string>>
  validation: ValidationState
  extraction: ExtractionState
  step: FlowStep
  /** Set from `advance` until it has gone to step `extract` or stopped with a message. */
  advancing: boolean
  /** A message for the user, ready to show; `null` when there is none. */
  message: string | null
}

/** What components can do with the flow. Each call leads straight to its function in `ProjectFlowProvider`. */
export type ProjectFlowActions = {
  /**
   * Adds dropped or chosen files in step `upload`. Files of another kind, empty, over 50 MB, with a name over 200
   * characters or a name the backend does not take (see `fileRejection`) are named in `message` and cause no request
   * (AC-19). Each other file is hashed, gets an upload URL
   * (a duplicate needs no upload) and is uploaded, at most 4 at a time; once none runs, one PATCH links them all.
   */
  addFiles(files: ArrayLike<File> | Iterable<File>): void
  /**
   * Removes a sheet by its `id`: a linked document with `DELETE /project/{id}/document/{documentId}`, a file of this
   * session by stopping its upload.
   */
  removeDocument(id: string): void
  /**
   * "Weiter zur Extraktion" (only when `selectCanAdvance`): removes every invalid document (AC-24), then goes to
   * step `extract`; when no valid document remains it stays and sets `message` (AC-25).
   */
  advance(): void
  /**
   * "Erneut prüfen" (only when `selectCanRetryValidation`): starts a new validation run, which opens the validation
   * stream again and clears the failure; the results documents already have are kept.
   */
  retryValidation(): void
  /** "Erneut versuchen" (only when `selectCanRetryExtraction`): starts the extraction again from the beginning. */
  retryExtraction(): void
}

/** The flow's state; read it with `useProjectFlowState`. */
export const ProjectFlowStateContext = createContext<ProjectFlowState | null>(null)

/** The flow's actions; read them with `useProjectFlowActions`. */
export const ProjectFlowActionsContext = createContext<ProjectFlowActions | null>(null)
