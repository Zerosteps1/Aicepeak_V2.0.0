import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/httpClient.ts'
import type { DocumentRef, Project } from '../../api/projects.ts'
import {
  CHECK_INTERRUPTED,
  discardedDocuments,
  EXTRACTION_FAILED,
  INITIAL_FLOW_STATE,
  linkRequest,
  matchLinked,
  NOT_LINKED,
  uploadsRejectedBy,
  uploadsToLink,
  withAdvanceOutcome,
  withExtractionEnd,
  withExtractionEvent,
  withExtractionReconnect,
  withExtractionRetry,
  withLinked,
  withLinkFailure,
  withProject,
  withValidationEnd,
  withValidationEvent,
  withValidationRetry,
} from './flowState.ts'
import type { LocalUpload, ProjectFlowState } from './projectFlowContext.ts'
import { selectCanAdvance, selectSheets } from './selectors.ts'

function ref(id: string, query = ''): DocumentRef {
  return { url: `https://store.example/tenant/p1/${id}${query}`, name: `${id}.pdf`, size: 10, contentType: 'application/pdf' }
}

function project(...documents: DocumentRef[]): Project {
  return { id: 'p1', name: 'Neues Projekt', startDate: '2026-11-19', endDate: null, description: '', documents }
}

function upload(localKey: string, change: Partial<LocalUpload> = {}): LocalUpload {
  return { localKey, file: new File(['x'], `${localKey}.pdf`), progress: 100, ref: null, error: null, ...change }
}

function state(change: Partial<ProjectFlowState> = {}): ProjectFlowState {
  return { ...INITIAL_FLOW_STATE, project: project(), ...change }
}

describe('linking uploads', () => {
  it('AC-16: links nothing while an upload runs, and never a failed one', () => {
    const done = upload('upload:1', { ref: ref('a') })
    const failed = upload('upload:2', { error: 'Hochladen fehlgeschlagen.' })

    expect(uploadsToLink(state({ uploads: { 'upload:1': done, 'upload:2': failed, 'upload:3': upload('upload:3') } }))).toEqual([])
    expect(uploadsToLink(state({ uploads: { 'upload:1': done, 'upload:2': failed } }))).toEqual([done])
  })

  it('AC-4: sends every document once, the project\'s first, all without a query', () => {
    const uploads = [upload('upload:1', { ref: ref('a', '?sig=secret') }), upload('upload:2', { ref: ref('d0') })]

    expect(linkRequest(project(ref('d0')), uploads)).toEqual({
      documents: [ref('d0'), ref('a')],
      owners: [null, 'upload:1'],
    })
  })

  it('matches each upload by URL, or by name and size when the backend linked a duplicate instead', () => {
    const replaced = { ...ref('older'), name: 'b.pdf', size: 20 }
    const uploads = [
      upload('upload:1', { ref: ref('a') }),
      upload('upload:2', { ref: { ...ref('b'), name: 'b.pdf', size: 20 } }),
      upload('upload:3', { ref: ref('lost') }),
    ]

    expect(matchLinked(uploads, project(ref('a'), replaced))).toEqual(
      new Map([
        ['upload:1', 'a'],
        ['upload:2', 'older'],
        ['upload:3', null],
      ]),
    )
  })

  it('AC-7: applies the PATCH answer, keeps the sheet keys and starts a new validation run', () => {
    const before = state({
      project: project(ref('d0')),
      uploads: { 'upload:1': upload('upload:1', { ref: ref('a') }), 'upload:2': upload('upload:2', { ref: ref('lost') }) },
      validation: { run: 3, status: 'done', error: null, documents: {} },
    })

    const after = withLinked(before, project(ref('d0'), ref('a')), new Map([['upload:1', 'a'], ['upload:2', null]]))

    expect(after.project?.documents).toEqual([ref('d0'), ref('a')])
    expect(after.uploads).toEqual({ 'upload:2': { ...before.uploads['upload:2'], ref: null, error: NOT_LINKED } })
    expect(after.sheetKeys).toEqual({ a: 'upload:1' })
    expect(after.validation).toMatchObject({ run: 4, status: 'running' })
  })

  it('unlinks after a PATCH only documents that removed uploads alone ended up as and the project did not have', () => {
    const matches = new Map<string, string | null>([
      ['upload:1', 'new'],
      ['upload:2', 'twice'],
      ['upload:3', 'twice'],
      ['upload:4', 'd0'],
      ['upload:5', null],
      ['upload:6', 'new'],
    ])
    const discarded = new Set(['upload:1', 'upload:2', 'upload:4', 'upload:5', 'upload:6'])

    expect(discardedDocuments(matches, discarded, new Set(['d0']))).toEqual(['new'])
    expect(discardedDocuments(matches, new Set(), new Set())).toEqual([])
  })

  it('fails the rejected uploads and always gives a new state, so the released ones are linked next', () => {
    const before = state({ uploads: { 'upload:1': upload('upload:1', { ref: ref('a') }), 'upload:2': upload('upload:2', { ref: ref('b') }) } })

    const failed = withLinkFailure(before, ['upload:1'])
    expect(failed.uploads).toEqual({
      'upload:1': { ...before.uploads['upload:1'], ref: null, error: NOT_LINKED },
      'upload:2': before.uploads['upload:2'],
    })

    // The rejected upload was removed while the PATCH ran: nothing to mark, but still a new state.
    const removedMeanwhile = withLinkFailure(before, ['upload:9'])
    expect(removedMeanwhile).not.toBe(before)
    expect(removedMeanwhile).toEqual(before)
  })

  it('puts a 400 down to the uploads its documents[i] fields name', () => {
    const owners = [null, 'upload:1', 'upload:2']
    const problem = (errors: Record<string, string[]>) => new ApiError('PATCH /project/{id}', 400, errors)

    expect(uploadsRejectedBy(problem({ 'documents[2].size': ['does not match the uploaded file'], 'documents[2].url': ['x'] }), owners)).toEqual(['upload:2'])
    expect(uploadsRejectedBy(problem({ 'documents[0].url': ['x'] }), owners)).toBeNull()
    expect(uploadsRejectedBy(problem({ name: ['x'] }), owners)).toBeNull()
    expect(uploadsRejectedBy(new ApiError('PATCH /project/{id}', 500), owners)).toBeNull()
    expect(uploadsRejectedBy(new TypeError('network'), owners)).toBeNull()
  })
})

describe('stream events', () => {
  const running = withProject(state({ project: null }), project(ref('d1')))

  it('starts the first validation run only for a project with documents', () => {
    expect(running.validation).toMatchObject({ run: 1, status: 'running' })
    expect(withProject(state({ project: null }), project()).validation).toMatchObject({ run: 0, status: 'idle' })
  })

  it('takes events of the current run for linked documents only, and ends with the 100 % event', () => {
    let next = withValidationEvent(running, 1, { overallProgress: 40, document: 'd1', documentProgress: 50 })
    next = withValidationEvent(next, 1, { overallProgress: 50, document: 'removed', documentProgress: 100 })
    next = withValidationEvent(next, 0, { overallProgress: 60, document: 'd1', error: 'stale run' })

    expect(next.validation.documents).toEqual({ d1: { progress: 50, error: null } })

    next = withValidationEvent(next, 1, { overallProgress: 100, document: 'd1', documentProgress: 100, error: 'Mock: kein Finanzbericht erkannt.' })
    expect(next.validation).toMatchObject({ status: 'done', documents: { d1: { progress: 100, error: 'Mock: kein Finanzbericht erkannt.' } } })
    expect(withValidationEnd(next, 1, null)).toBe(next)
  })

  it('fails the run on a run error or a stream that ends early', () => {
    expect(withValidationEvent(running, 1, { overallProgress: 10, document: '', error: 'Analyse nicht verfügbar' }).validation).toMatchObject({
      status: 'failed',
      error: 'Analyse nicht verfügbar',
    })
    expect(withValidationEnd(running, 1, null).validation).toMatchObject({ status: 'failed', error: 'Die Prüfung wurde unterbrochen.' })
  })

  it('AC-21: records pages, counters and every position of the extraction', () => {
    const extracting = { ...running, step: 'extract' as const, extraction: { ...running.extraction, run: 1, status: 'running' as const } }
    const position = { name: 'Umsatzerlöse', value: 184300, period: '2025', source: 'GuV', page: 1 }

    let next = withExtractionEvent(extracting, 1, { overallProgress: 10, document: 'd1', pages: 3, pagesRead: 1, positions: 2, position })
    next = withExtractionEvent(next, 1, { overallProgress: 100, document: 'd1', pagesRead: 3, positions: 6 })

    expect(next.extraction).toEqual({
      run: 1,
      status: 'done',
      error: null,
      overallProgress: 100,
      positions: 6,
      documents: { d1: { pages: 3, pagesRead: 3, progress: 0, error: null } },
      found: [{ ...position, documentId: 'd1' }],
    })
    expect(withExtractionEnd(extracting, 1, null).extraction).toMatchObject({ status: 'failed', error: 'Die Extraktion wurde unterbrochen.' })
  })
})

describe('retrying a failed run', () => {
  const position = { name: 'Umsatzerlöse', value: 184300, period: '2025', source: 'GuV', page: 1 }

  it('keeps documents without a result failed after the stream gave up, which blocks advancing', () => {
    let next = withProject(state({ project: null }), project(ref('d1'), ref('d2')))
    next = withValidationEvent(next, 1, { overallProgress: 50, document: 'd1', documentProgress: 100 })
    next = withValidationEnd(next, 1, null)

    expect(selectSheets(next).map(({ id, status, error }) => ({ id, status, error }))).toEqual([
      { id: 'd1', status: 'valid', error: null },
      { id: 'd2', status: 'failed', error: CHECK_INTERRUPTED },
    ])
    expect(selectCanAdvance(next)).toBe(false)
  })

  it('starts a new validation run that clears the failure and keeps the results', () => {
    let failed = withProject(state({ project: null }), project(ref('d1'), ref('d2')))
    failed = withValidationEvent(failed, 1, { overallProgress: 50, document: 'd1', documentProgress: 100 })
    failed = withValidationEvent(failed, 1, { overallProgress: 100, document: '', error: 'Analyse nicht verfügbar' })

    const retried = withValidationRetry(failed)

    expect(retried.validation).toEqual({ run: 2, status: 'running', error: null, documents: { d1: { progress: 100, error: null } } })
    expect(selectSheets(retried).map((sheet) => sheet.status)).toEqual(['valid', 'queued'])
    // Events of the failed run no longer count; the new run's do.
    expect(withValidationEvent(retried, 1, { overallProgress: 100, document: 'd2', documentProgress: 100 })).toBe(retried)
    expect(withValidationEvent(retried, 2, { overallProgress: 100, document: 'd2', documentProgress: 100 }).validation.status).toBe('done')
  })

  it('does not retry the validation while it runs, once every document has its result, or after advance started', () => {
    const running = withProject(state({ project: null }), project(ref('d1')))
    const done = withValidationEvent(running, 1, { overallProgress: 100, document: 'd1', documentProgress: 100 })
    const failed = withValidationEnd(running, 1, null)

    expect(withValidationRetry(running)).toBe(running)
    expect(withValidationRetry(done)).toBe(done)
    expect(withValidationRetry({ ...failed, advancing: true }).validation.run).toBe(1)
    expect(withValidationRetry(failed).validation.run).toBe(2)
  })

  it('counts extraction runs and ignores events and ends of older runs', () => {
    const validated = withValidationEvent(withProject(state({ project: null }), project(ref('d1'))), 1, { overallProgress: 100, document: 'd1', documentProgress: 100 })
    const extracting = withAdvanceOutcome(validated, true)
    expect(extracting.extraction).toMatchObject({ run: 1, status: 'running' })

    const failed = withExtractionEnd(withExtractionEvent(extracting, 1, { overallProgress: 40, document: 'd1', pages: 3, pagesRead: 1, positions: 1, position }), 1, EXTRACTION_FAILED)
    expect(failed.extraction).toMatchObject({ run: 1, status: 'failed', error: EXTRACTION_FAILED, found: [{ ...position, documentId: 'd1' }] })

    const retried = withExtractionRetry(failed)
    expect(retried.extraction).toEqual({ run: 2, status: 'running', error: null, overallProgress: 0, positions: 0, documents: {}, found: [] })
    expect(withExtractionEvent(retried, 1, { overallProgress: 100, document: 'd1', pagesRead: 3 })).toBe(retried)
    expect(withExtractionEnd(retried, 1, EXTRACTION_FAILED)).toBe(retried)
    expect(withExtractionEvent(retried, 2, { overallProgress: 100, document: 'd1', pages: 3, pagesRead: 3 }).extraction).toMatchObject({ run: 2, status: 'done' })
  })

  it('does not retry the extraction while it runs, once done, or in step upload', () => {
    const validated = withValidationEvent(withProject(state({ project: null }), project(ref('d1'))), 1, { overallProgress: 100, document: 'd1', documentProgress: 100 })
    const extracting = withAdvanceOutcome(validated, true)
    const done = withExtractionEvent(extracting, 1, { overallProgress: 100, document: 'd1', pages: 1, pagesRead: 1 })
    const failedInUpload = { ...validated, extraction: { ...validated.extraction, status: 'failed' as const } }

    expect(withExtractionRetry(extracting)).toBe(extracting)
    expect(withExtractionRetry(done)).toBe(done)
    expect(withExtractionRetry(failedInUpload)).toBe(failedInUpload)
  })

  it('starts the progress of an extraction over when its stream reconnects, so nothing is counted twice', () => {
    const validated = withValidationEvent(withProject(state({ project: null }), project(ref('d1'))), 1, { overallProgress: 100, document: 'd1', documentProgress: 100 })
    const extracting = withExtractionEvent(withAdvanceOutcome(validated, true), 1, { overallProgress: 40, document: 'd1', pages: 3, pagesRead: 1, positions: 1, position })

    const reconnected = withExtractionReconnect(extracting, 1)

    expect(reconnected.extraction).toEqual({ run: 1, status: 'running', error: null, overallProgress: 0, positions: 0, documents: {}, found: [] })
    expect(withExtractionReconnect(extracting, 0)).toBe(extracting)
    const failed = withExtractionEnd(extracting, 1, null)
    expect(withExtractionReconnect(failed, 1)).toBe(failed)
  })
})
