import { useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { deleteDocument, documentIdOf } from '../../api/documents.ts'
import { readExtractionRun, readValidationRun } from '../../api/documentStreams.ts'
import { ApiError } from '../../api/httpClient.ts'
import { getProject, patchProject } from '../../api/projects.ts'
import { createSerialQueue, createTaskLimiter, type SerialQueue } from './concurrency.ts'
import { fileRejection, rejectionMessage } from './files.ts'
import {
  discardedDocuments,
  EXTRACTION_FAILED,
  INITIAL_FLOW_STATE,
  linkRequest,
  matchLinked,
  PROJECT_LOAD_FAILED,
  PROJECT_NOT_FOUND,
  UPLOAD_FAILED,
  uploadsRejectedBy,
  uploadsToLink,
  withAddedUploads,
  withAdvanceOutcome,
  withAdvancing,
  withExtractionEnd,
  withExtractionEvent,
  withExtractionReconnect,
  withExtractionRetry,
  withLinked,
  withLinkFailure,
  withLoadError,
  withoutUpload,
  withProject,
  withRemoving,
  withUnlinked,
  withUnlinkFailure,
  withUploadChange,
  withValidationEnd,
  withValidationEvent,
  withValidationRetry,
} from './flowState.ts'
import {
  ProjectFlowActionsContext,
  ProjectFlowStateContext,
  type LocalUpload,
  type ProjectFlowActions,
  type ProjectFlowState,
} from './projectFlowContext.ts'
import { CHECK_FAILED, selectCanAdvance, selectInvalidDocumentIds, selectIsLinked } from './selectors.ts'
import { uploadDocument } from './uploadDocument.ts'

/** Files uploaded at the same time, at most. */
export const MAX_PARALLEL_UPLOADS = 4

let uploadCount = 0

/** A key for a file of this session; `upload:` never looks like a documentId (a GUID). */
function nextLocalKey(): string {
  uploadCount += 1
  return `upload:${uploadCount}`
}

/** What a PATCH or DELETE of this provider needs besides its own arguments. */
type ServerRequests = {
  projectId: string
  setState: Dispatch<SetStateAction<ProjectFlowState>>
  /** PATCH and DELETE requests go through it, so they never overlap. */
  queue: SerialQueue
  signal: AbortSignal | undefined
}

/**
 * Sends `DELETE /project/{id}/document/{documentId}` after the requests queued before it. The sheet is hidden while
 * it runs; a 404 means the document is no longer linked, which is what was wanted. Resolves with whether the document
 * is gone.
 */
function unlinkDocument({ projectId, setState, queue, signal }: ServerRequests, documentId: string): Promise<boolean> {
  setState((prev) => withRemoving(prev, documentId))
  return queue.run(() => deleteDocument(projectId, documentId, signal)).then(
    () => true,
    (error: unknown) => error instanceof ApiError && error.status === 404,
  ).then((removed) => {
    if (!signal?.aborted) {
      setState((prev) => (removed ? withUnlinked(prev, documentId) : withUnlinkFailure(prev, documentId)))
    }
    return removed
  })
}

type ProjectFlowProviderProps = {
  projectId: string
  children: ReactNode
}

/**
 * The single source of state of the "Neues Projekt" flow for one project; it renders nothing itself. Components read
 * the state with `useProjectFlowState`, derive what they show with `selectors.ts` and call the plain functions of
 * `useProjectFlowActions`.
 *
 * It loads the project; once no upload runs, it links all finished uploads with one PATCH and opens the validation
 * stream again after each PATCH (AC-7); in step `extract` it reads the extraction stream. A broken stream reconnects up
 * to 3 times (see `readWithReconnect`); after that the run has failed until `retryValidation` or `retryExtraction`
 * starts it again. PATCH and DELETE requests run one after another. Unmounting aborts every request, upload and stream.
 */
export function ProjectFlowProvider({ projectId, children }: ProjectFlowProviderProps) {
  // Another project starts from a fresh state: nothing of the previous one is kept.
  return (
    <ProjectFlowScope key={projectId} projectId={projectId}>
      {children}
    </ProjectFlowScope>
  )
}

function ProjectFlowScope({ projectId, children }: ProjectFlowProviderProps) {
  const [state, setState] = useState<ProjectFlowState>(INITIAL_FLOW_STATE)
  // Bookkeeping of running requests below. React never renders it, so it is not state.
  /** Aborted on unmount; PATCH and DELETE requests use its signal. */
  const lifetime = useRef<AbortController | null>(null)
  const serverQueue = useRef(createSerialQueue())
  const uploadLimiter = useRef(createTaskLimiter(MAX_PARALLEL_UPLOADS))
  /** By local key, while the upload waits or runs. */
  const uploadControllers = useRef(new Map<string, AbortController>())
  /** Local keys a PATCH has been sent for, so no upload is ever sent twice. */
  const linkSent = useRef(new Set<string>())
  /**
   * Local keys removed by the user; if a running PATCH links one anyway, its document is removed afterwards, unless
   * the project had it before or another upload of that PATCH is the same document (see `discardedDocuments`).
   */
  const discarded = useRef(new Set<string>())

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    const uploads = uploadControllers.current
    return () => {
      controller.abort()
      uploads.forEach((upload) => upload.abort())
      uploads.clear()
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    getProject(projectId, controller.signal).then(
      (project) => {
        if (!controller.signal.aborted) {
          setState((prev) => withProject(prev, project))
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          const notFound = error instanceof ApiError && error.status === 404
          setState((prev) => withLoadError(prev, notFound ? PROJECT_NOT_FOUND : PROJECT_LOAD_FAILED))
        }
      },
    )
    return () => controller.abort()
  }, [projectId])

  // One PATCH for all finished uploads, once none runs and no other PATCH or DELETE waits or runs (AC-4, AC-16).
  useEffect(() => {
    const project = state.project
    const queue = serverQueue.current
    const sent = linkSent.current
    const uploads = uploadsToLink(state).filter((upload) => !sent.has(upload.localKey))
    if (project === null || state.step !== 'upload' || uploads.length === 0 || !queue.idle) {
      return
    }
    uploads.forEach((upload) => sent.add(upload.localKey))
    const { documents, owners } = linkRequest(project, uploads)
    const linkedBefore = new Set(project.documents.map((ref) => documentIdOf(ref.url)))
    const signal = lifetime.current?.signal
    queue.run(() => patchProject(projectId, { documents }, signal)).then(
      (updated) => {
        if (signal?.aborted) {
          return
        }
        const matches = matchLinked(uploads, updated)
        setState((prev) => withLinked(prev, updated, matches))
        for (const documentId of discardedDocuments(matches, discarded.current, linkedBefore)) {
          void unlinkDocument({ projectId, setState, queue, signal }, documentId)
        }
      },
      (error: unknown) => {
        if (signal?.aborted) {
          return
        }
        const rejected = uploadsRejectedBy(error, owners) ?? uploads.map((upload) => upload.localKey)
        for (const upload of uploads) {
          if (!rejected.includes(upload.localKey)) {
            // Not at fault: it goes with the next PATCH.
            sent.delete(upload.localKey)
          }
        }
        // A new state even when every rejected upload was removed meanwhile, so the released ones are linked next.
        setState((prev) => withLinkFailure(prev, rejected))
      },
    )
  }, [projectId, state])

  // The validation stream, opened again for every run (AC-7, `retryValidation`) while in step `upload`; a broken
  // stream reconnects within the run.
  const validationRun = state.validation.run
  const validating = state.step === 'upload' && validationRun > 0
  useEffect(() => {
    if (!validating) {
      return
    }
    const controller = new AbortController()
    const signal = controller.signal
    readValidationRun(
      projectId,
      (event) => {
        if (!signal.aborted) {
          setState((prev) => withValidationEvent(prev, validationRun, event))
        }
      },
      { signal },
    ).then(
      () => {
        if (!signal.aborted) {
          setState((prev) => withValidationEnd(prev, validationRun, null))
        }
      },
      () => {
        if (!signal.aborted) {
          setState((prev) => withValidationEnd(prev, validationRun, CHECK_FAILED))
        }
      },
    )
    return () => controller.abort()
  }, [projectId, validationRun, validating])

  // The extraction stream, opened for every run (`advance`, `retryExtraction`) in step `extract`; a broken stream
  // reconnects within the run and starts its progress over.
  const extractionRun = state.extraction.run
  const extracting = state.step === 'extract' && extractionRun > 0
  useEffect(() => {
    if (!extracting) {
      return
    }
    const controller = new AbortController()
    const signal = controller.signal
    readExtractionRun(
      projectId,
      (event) => {
        if (!signal.aborted) {
          setState((prev) => withExtractionEvent(prev, extractionRun, event))
        }
      },
      {
        signal,
        onReconnect: () => {
          if (!signal.aborted) {
            setState((prev) => withExtractionReconnect(prev, extractionRun))
          }
        },
      },
    ).then(
      () => {
        if (!signal.aborted) {
          setState((prev) => withExtractionEnd(prev, extractionRun, null))
        }
      },
      () => {
        if (!signal.aborted) {
          setState((prev) => withExtractionEnd(prev, extractionRun, EXTRACTION_FAILED))
        }
      },
    )
    return () => controller.abort()
  }, [projectId, extractionRun, extracting])

  // Plain functions over the current state; each call leads straight to its requests. They read the state of this
  // render (e.g. which documents `advance` removes), so the object changes with the state instead of mirroring it.
  const actions = useMemo<ProjectFlowActions>(() => {
    const serverRequests = (): ServerRequests => ({
      projectId,
      setState,
      queue: serverQueue.current,
      signal: lifetime.current?.signal,
    })

    function startUpload({ localKey, file }: LocalUpload) {
      const controller = new AbortController()
      const controllers = uploadControllers.current
      controllers.set(localKey, controller)
      uploadLimiter.current
        .run(() =>
          uploadDocument(projectId, file, {
            signal: controller.signal,
            onProgress: (progress) => setState((prev) => withUploadChange(prev, localKey, { progress })),
          }),
        )
        .then(
          (ref) => setState((prev) => withUploadChange(prev, localKey, { ref, progress: 100 })),
          () => {
            if (!controller.signal.aborted) {
              setState((prev) => withUploadChange(prev, localKey, { error: UPLOAD_FAILED }))
            }
          },
        )
        .finally(() => controllers.delete(localKey))
    }

    return {
      addFiles(files) {
        if (state.project === null || state.step !== 'upload' || state.advancing) {
          return
        }
        const all = Array.from(files)
        const rejected = all.filter((file) => fileRejection(file) !== null)
        const added = all
          .filter((file) => fileRejection(file) === null)
          .map((file): LocalUpload => ({ localKey: nextLocalKey(), file, progress: 0, ref: null, error: null }))
        const message = rejected.length > 0 ? rejectionMessage(rejected.map((file) => file.name)) : null
        setState((prev) => withAddedUploads(prev, added, message))
        added.forEach(startUpload)
      },

      removeDocument(id) {
        if (Object.hasOwn(state.uploads, id)) {
          uploadControllers.current.get(id)?.abort()
          discarded.current.add(id)
          setState((prev) => withoutUpload(prev, id))
          return
        }
        if (state.step === 'upload' && !state.removing.includes(id) && selectIsLinked(state, id)) {
          void unlinkDocument(serverRequests(), id)
        }
      },

      advance() {
        if (!selectCanAdvance(state)) {
          return
        }
        const invalid = selectInvalidDocumentIds(state)
        const requests = serverRequests()
        setState(withAdvancing)
        void Promise.all(invalid.map((documentId) => unlinkDocument(requests, documentId))).then((removed) => {
          if (!requests.signal?.aborted) {
            setState((prev) => withAdvanceOutcome(prev, removed.every(Boolean)))
          }
        })
      },

      retryValidation() {
        // A new run: the validation effect opens the stream again for it.
        setState(withValidationRetry)
      },

      retryExtraction() {
        // A new run: the extraction effect opens the stream again for it.
        setState(withExtractionRetry)
      },
    }
  }, [projectId, state])

  return (
    <ProjectFlowStateContext value={state}>
      <ProjectFlowActionsContext value={actions}>{children}</ProjectFlowActionsContext>
    </ProjectFlowStateContext>
  )
}
