import { describe, expect, it } from 'vitest'
import type { DocumentRef, Project } from '../../api/projects.ts'
import { INITIAL_FLOW_STATE } from './flowState.ts'
import type { DocumentCheck, FoundPosition, LocalUpload, ProjectFlowState } from './projectFlowContext.ts'
import {
  selectCanAdvance,
  selectCanRetryExtraction,
  selectCanRetryValidation,
  selectExtractionLines,
  selectExtractionSummary,
  selectHasValidDocument,
  selectInvalidDocumentIds,
  selectLatestPositions,
  selectSheets,
  selectUploadHint,
  selectUploadTotals,
} from './selectors.ts'

function ref(id: string, size = 1024 * 1024): DocumentRef {
  return { url: `https://store.example/tenant/p1/${id}`, name: `${id}.pdf`, size, contentType: 'application/pdf' }
}

function project(...documents: DocumentRef[]): Project {
  return { id: 'p1', name: 'Neues Projekt', startDate: '2026-11-19', endDate: null, description: '', documents }
}

function upload(localKey: string, change: Partial<LocalUpload> = {}): LocalUpload {
  return { localKey, file: new File(['x'.repeat(512 * 1024)], `${localKey.replace(':', '-')}.xlsx`), progress: 0, ref: null, error: null, ...change }
}

function flow(change: Partial<ProjectFlowState> = {}, checks: Record<string, DocumentCheck> = {}): ProjectFlowState {
  return {
    ...INITIAL_FLOW_STATE,
    project: project(),
    ...change,
    validation: { run: 1, status: 'running', error: null, ...change.validation, documents: { ...change.validation?.documents, ...checks } },
  }
}

const VALID = { progress: 100, error: null }
const INVALID = { progress: 100, error: 'Mock: kein Finanzbericht erkannt.' }

describe('selectSheets', () => {
  it('derives each status from uploads and validation events', () => {
    const state = flow(
      {
        project: project(ref('d-queued'), ref('d-checking'), ref('d-valid'), ref('d-invalid')),
        uploads: {
          'upload:1': upload('upload:1', { progress: 42 }),
          'upload:2': upload('upload:2', { progress: 100, ref: ref('d-new') }),
          'upload:3': upload('upload:3', { error: 'Hochladen fehlgeschlagen.' }),
        },
      },
      { 'd-checking': { progress: 50, error: null }, 'd-valid': VALID, 'd-invalid': INVALID },
    )

    expect(selectSheets(state).map(({ id, status, progress, error }) => ({ id, status, progress, error }))).toEqual([
      { id: 'd-queued', status: 'queued', progress: 0, error: null },
      { id: 'd-checking', status: 'checking', progress: 50, error: null },
      { id: 'd-valid', status: 'valid', progress: 100, error: null },
      { id: 'd-invalid', status: 'invalid', progress: 100, error: 'Mock: kein Finanzbericht erkannt.' },
      { id: 'upload:1', status: 'uploading', progress: 42, error: null },
      { id: 'upload:2', status: 'queued', progress: 100, error: null },
      { id: 'upload:3', status: 'failed', progress: 0, error: 'Hochladen fehlgeschlagen.' },
    ])
  })

  it('marks linked documents without a result as failed once the run failed or ended', () => {
    const failed = flow({ project: project(ref('d1'), ref('d2')), validation: { run: 1, status: 'failed', error: 'Die Prüfung wurde unterbrochen.', documents: {} } }, { d2: VALID })

    expect(selectSheets(failed).map(({ status, error }) => ({ status, error }))).toEqual([
      { status: 'failed', error: 'Die Prüfung wurde unterbrochen.' },
      { status: 'valid', error: null },
    ])
  })

  it('hides documents being removed and keeps the local key of linked uploads as React key', () => {
    const state = flow({ project: project(ref('d1'), ref('d2')), removing: ['d1'], sheetKeys: { d2: 'upload:7' } })

    expect(selectSheets(state).map(({ key, id, documentId, kind }) => ({ key, id, documentId, kind }))).toEqual([
      { key: 'upload:7', id: 'd2', documentId: 'd2', kind: 'PDF' },
    ])
  })
})

describe('selectCanAdvance', () => {
  const linked = { project: project(ref('d1'), ref('d2')) }

  it('AC-23: is available once every document is uploaded, linked and checked', () => {
    expect(selectCanAdvance(flow(linked, { d1: VALID, d2: VALID }))).toBe(true)
    expect(selectCanAdvance(flow(linked, { d1: VALID, d2: INVALID }))).toBe(true)
  })

  it('AC-23: is available when all documents are invalid, so advance can say so (AC-25)', () => {
    expect(selectCanAdvance(flow(linked, { d1: INVALID, d2: INVALID }))).toBe(true)
  })

  it('AC-23: is not available without documents or before the project has loaded', () => {
    expect(selectCanAdvance(flow())).toBe(false)
    expect(selectCanAdvance({ ...INITIAL_FLOW_STATE })).toBe(false)
  })

  it.each([
    ['a document is still being checked', flow(linked, { d1: VALID, d2: { progress: 75, error: null } })],
    ['a document waits to be checked', flow(linked, { d1: VALID })],
    ['an upload runs', flow({ ...linked, uploads: { 'upload:1': upload('upload:1') } }, { d1: VALID, d2: VALID })],
    ['an upload waits to be linked', flow({ ...linked, uploads: { 'upload:1': upload('upload:1', { ref: ref('d3') }) } }, { d1: VALID, d2: VALID })],
    ['a linked document has no check result', flow({ ...linked, validation: { run: 1, status: 'failed', error: null, documents: {} } }, { d1: VALID })],
    ['a removal runs', flow({ ...linked, removing: ['d2'] }, { d1: VALID })],
    ['advance runs', flow({ ...linked, advancing: true }, { d1: VALID, d2: VALID })],
    ['the step is extract', flow({ ...linked, step: 'extract' }, { d1: VALID, d2: VALID })],
  ])('AC-23: is not available while %s', (_case, state) => {
    expect(selectCanAdvance(state)).toBe(false)
  })

  it('AC-23: a failed upload blocks nothing', () => {
    const state = flow({ ...linked, uploads: { 'upload:1': upload('upload:1', { error: 'Hochladen fehlgeschlagen.' }) } }, { d1: VALID, d2: VALID })

    expect(selectCanAdvance(state)).toBe(true)
  })

  it('AC-24: names the invalid documents and whether a valid one is left', () => {
    const state = flow(linked, { d1: VALID, d2: INVALID })

    expect(selectInvalidDocumentIds(state)).toEqual(['d2'])
    expect(selectHasValidDocument(state)).toBe(true)
    expect(selectHasValidDocument(flow(linked, { d1: INVALID, d2: INVALID }))).toBe(false)
  })
})

describe('retrying', () => {
  const linked = { project: project(ref('d1'), ref('d2')) }
  const failedRun = { run: 1, status: 'failed' as const, error: 'Die Prüfung wurde unterbrochen.', documents: {} }

  it('offers checking again while a linked document has no result after its run failed or ended', () => {
    expect(selectCanRetryValidation(flow({ ...linked, validation: failedRun }, { d1: VALID }))).toBe(true)
    expect(selectCanRetryValidation(flow({ ...linked, validation: { ...failedRun, status: 'done', error: null } }, { d1: VALID }))).toBe(true)
  })

  it.each([
    ['the run is still going', flow(linked, { d1: VALID })],
    ['every document has its result despite the failure', flow({ ...linked, validation: failedRun }, { d1: VALID, d2: INVALID })],
    ['the document without a result is being removed', flow({ ...linked, validation: failedRun, removing: ['d2'] }, { d1: VALID })],
    ['only an upload failed', flow({ uploads: { 'upload:1': upload('upload:1', { error: 'Hochladen fehlgeschlagen.' }) } })],
    ['advance runs', flow({ ...linked, validation: failedRun, advancing: true }, { d1: VALID })],
    ['the step is extract', flow({ ...linked, validation: failedRun, step: 'extract' }, { d1: VALID })],
  ])('does not offer checking again while %s', (_case, state) => {
    expect(selectCanRetryValidation(state)).toBe(false)
  })

  it('offers extracting again only in step extract once the run failed', () => {
    const extraction = (status: 'running' | 'done' | 'failed') => ({ ...INITIAL_FLOW_STATE.extraction, run: 1, status })

    expect(selectCanRetryExtraction(flow({ ...linked, step: 'extract', extraction: extraction('failed') }))).toBe(true)
    expect(selectCanRetryExtraction(flow({ ...linked, step: 'extract', extraction: extraction('running') }))).toBe(false)
    expect(selectCanRetryExtraction(flow({ ...linked, step: 'extract', extraction: extraction('done') }))).toBe(false)
    expect(selectCanRetryExtraction(flow({ ...linked, step: 'upload', extraction: extraction('failed') }))).toBe(false)
  })
})

describe('upload hints and totals', () => {
  it('counts the documents and their size in MB', () => {
    expect(selectUploadTotals(flow()).label).toBe('Noch keine Dokumente')
    const state = flow({ project: project(ref('d1')), uploads: { 'upload:1': upload('upload:1') } })
    expect(selectUploadTotals(state)).toEqual({ documents: 2, bytes: 1.5 * 1024 * 1024, label: '2 Dokumente · 1,5 MB' })
  })

  it.each([
    ['no documents', flow(), 'Weiter, sobald alle Dokumente geprüft sind.'],
    ['uploading', flow({ uploads: { 'upload:1': upload('upload:1') } }), 'Dokumente werden hochgeladen …'],
    ['checking', flow({ project: project(ref('d1')) }), 'Dokumente werden geprüft …'],
    ['a check failed', flow({ project: project(ref('d1')), validation: { run: 1, status: 'done', error: null, documents: {} } }), 'Die Prüfung ist fehlgeschlagen. Bitte prüfen Sie erneut oder entfernen Sie die betroffenen Dokumente.'],
    ['a check failed while advance runs', flow({ project: project(ref('d1')), advancing: true, validation: { run: 1, status: 'failed', error: null, documents: {} } }), 'Die Prüfung ist fehlgeschlagen. Bitte entfernen Sie die betroffenen Dokumente.'],
    ['none valid', flow({ project: project(ref('d1')) }, { d1: INVALID }), 'Keines der Dokumente enthält einen Finanzbericht.'],
    ['some valid', flow({ project: project(ref('d1'), ref('d2')) }, { d1: VALID, d2: INVALID }), '1 von 2 Dokumenten werden verwendet.'],
    ['all valid', flow({ project: project(ref('d1')) }, { d1: VALID }), 'Alle Dokumente geprüft.'],
    ['a message', flow({ message: 'Keines der Dokumente ist verwendbar.' }), 'Keines der Dokumente ist verwendbar.'],
    ['a load error', { ...INITIAL_FLOW_STATE, loadError: 'Das Projekt wurde nicht gefunden.' }, 'Das Projekt wurde nicht gefunden.'],
  ])('says how far the documents are: %s', (_case, state, hint) => {
    expect(selectUploadHint(state)).toBe(hint)
  })
})

describe('extraction', () => {
  function extracting(documents: ProjectFlowState['extraction']['documents'], found: FoundPosition[] = [], status: 'running' | 'done' = 'running') {
    return flow(
      { project: project(ref('d1'), ref('d2'), ref('d3'), ref('d-invalid')), step: 'extract', extraction: { run: 1, status, error: null, overallProgress: 40, positions: 12, documents, found } },
      { d1: VALID, d2: VALID, d3: VALID, 'd-invalid': INVALID },
    )
  }

  it('AC-21: gives one line per valid document with a segment per page and the page being read', () => {
    const state = extracting({
      d1: { pages: 3, pagesRead: 1, progress: 33, error: null },
      d2: { pages: 151, pagesRead: 30, progress: 20, error: null },
    })

    const lines = selectExtractionLines(state)

    expect(lines.map((line) => line.documentId)).toEqual(['d1', 'd2', 'd3'])
    expect(lines[0]).toMatchObject({ pages: 3, pagesRead: 1, reading: true, track: { kind: 'segments', segments: ['done', 'now', 'todo'] } })
    expect(lines[1]).toMatchObject({ reading: true, track: { kind: 'strip', read: 30 / 151 } })
    expect(lines[2]).toMatchObject({ pages: null, pagesRead: 0, reading: false, track: { kind: 'segments', segments: [] } })
  })

  it('AC-21: uses segments up to 150 pages and stops reading once a document is read', () => {
    const state = extracting({ d1: { pages: 150, pagesRead: 150, progress: 100, error: null } }, [], 'done')

    const [line] = selectExtractionLines(state)

    expect(line?.reading).toBe(false)
    expect(line?.track).toEqual({ kind: 'segments', segments: Array.from({ length: 150 }, () => 'done') })
  })

  it('AC-21: sums pages and positions and unlocks the positions once done', () => {
    const running = extracting({ d1: { pages: 3, pagesRead: 2, progress: 66, error: null }, d2: { pages: 6, pagesRead: 0, progress: 0, error: null } })

    expect(selectExtractionSummary(running)).toEqual({
      status: 'running',
      documents: 3,
      pages: 9,
      pagesRead: 2,
      positions: 12,
      label: '3 Dokumente · 9 Seiten',
      hint: 'Verfügbar, sobald alle Seiten gelesen sind.',
      canContinue: false,
    })
    expect(selectExtractionSummary(extracting({}, [], 'done'))).toMatchObject({ hint: 'Alle Seiten gelesen.', canContinue: true })
  })

  it('AC-21: shows the latest three positions, newest first', () => {
    const found = [1, 2, 3, 4].map((page): FoundPosition => ({ documentId: 'd1', name: `Position ${page}`, value: page, period: '2025', source: 'GuV', page }))

    expect(selectLatestPositions(extracting({}, found)).map((position) => position.page)).toEqual([4, 3, 2])
  })
})
