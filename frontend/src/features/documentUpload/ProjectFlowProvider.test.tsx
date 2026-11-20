import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessTokenProvider } from '../../api/httpClient.ts'
import type { DocumentRef, Project } from '../../api/projects.ts'
import { deferred } from '../../test/deferred.ts'
import { FakeEventStream, json, stubApi, validationProblem, type RecordedRequest } from '../../test/fakeApi.ts'
import { fakeSha256, stubDigest } from '../../test/fakeCrypto.ts'
import { stubXhr, type FakeXhr } from '../../test/fakeXhr.ts'
import { CHECK_INTERRUPTED, EXTRACTION_FAILED, NO_VALID_DOCUMENT, NOT_LINKED, PROJECT_NOT_FOUND, UPLOAD_FAILED } from './flowState.ts'
import { ProjectFlowProvider } from './ProjectFlowProvider.tsx'
import { CHECK_FAILED, selectCanAdvance, selectCanRetryExtraction, selectCanRetryValidation, selectExtractionLines, selectSheets } from './selectors.ts'
import { useProjectFlowActions, useProjectFlowState } from './useProjectFlow.ts'

/** The waits before stream reconnects, recorded instead of waited for, so the tests need no timers. */
const reconnectWaits = vi.hoisted((): number[] => [])

vi.mock('../../api/documentStreams.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/documentStreams.ts')>()
  const sleep = async (ms: number, signal?: AbortSignal) => {
    reconnectWaits.push(ms)
    signal?.throwIfAborted()
  }
  return {
    ...actual,
    readValidationRun: (...[projectId, onEvent, options]: Parameters<typeof actual.readValidationRun>) =>
      actual.readValidationRun(projectId, onEvent, { ...options, sleep }),
    readExtractionRun: (...[projectId, onEvent, options]: Parameters<typeof actual.readExtractionRun>) =>
      actual.readExtractionRun(projectId, onEvent, { ...options, sleep }),
  }
})

const PROJECT_ID = '0195f3a2-0000-7000-8000-0000000000aa'
const PROJECT_PATH = `/project/${PROJECT_ID}`
const VALIDATION_PATH = `${PROJECT_PATH}/document-validation/sse`
const EXTRACTION_PATH = `${PROJECT_PATH}/document-extraction/sse`
const EXPIRES = new Date(Date.now() + 15 * 60_000).toISOString()

/** The blob URL of a document of this project, without query. */
function documentUrl(documentId: string): string {
  return `https://store.example/tenant/${PROJECT_ID}/${documentId}`
}

function linked(documentId: string, name = `${documentId}.pdf`, size = 10): DocumentRef {
  return { url: documentUrl(documentId), name, size, contentType: 'application/pdf' }
}

/** A file whose upload becomes documentId `doc-<base name>`. */
function pdf(baseName: string, content = `%PDF ${baseName}`): File {
  return new File([content], `${baseName}.pdf`)
}

type Backend = {
  project: Project
  /** Overrides the PATCH answer; by default the backend stores the body's documents. */
  patch?: (request: RecordedRequest) => Response | Promise<Response>
}

function setup(documents: DocumentRef[] = [], { strict = false } = {}) {
  stubDigest()
  const api = stubApi()
  const xhr = stubXhr()
  const backend: Backend = {
    project: { id: PROJECT_ID, name: 'Neues Projekt', startDate: '2026-11-19', endDate: null, description: '', documents },
  }
  api.on('GET', PROJECT_PATH, () => json(backend.project))
  api.on('POST', `${PROJECT_PATH}/upload-url`, (request) => {
    const { name } = request.body as { name: string }
    const documentId = `doc-${name.replace(/\.[^.]+$/, '')}`
    return json({ blobUrl: `${documentUrl(documentId)}?sv=2025-01-05&sr=b&sp=c&sig=secret`, expires: EXPIRES })
  })
  api.on('PATCH', PROJECT_PATH, (request) => {
    if (backend.patch) {
      return backend.patch(request)
    }
    backend.project = { ...backend.project, documents: (request.body as { documents: DocumentRef[] }).documents }
    return json(backend.project)
  })
  api.on('DELETE', new RegExp(`^${PROJECT_PATH}/document/`), (request) => {
    const documentId = request.path.split('/').pop()
    backend.project = { ...backend.project, documents: backend.project.documents.filter((ref) => !ref.url.endsWith(`/${documentId}`)) }
    return new Response(null, { status: 204 })
  })
  const validations = api.streams(VALIDATION_PATH)
  const extractions = api.streams(EXTRACTION_PATH)

  const wrapper = ({ children }: { children: ReactNode }) => {
    const provider = <ProjectFlowProvider projectId={PROJECT_ID}>{children}</ProjectFlowProvider>
    return strict ? <StrictMode>{provider}</StrictMode> : provider
  }
  const hook = renderHook(() => ({ state: useProjectFlowState(), actions: useProjectFlowActions() }), { wrapper })
  return { api, xhr, backend, validations, extractions, hook }
}

type Flow = ReturnType<typeof setup>

async function loaded(flow: Flow) {
  await waitFor(() => expect(flow.hook.result.current.state.project).not.toBeNull())
}

/** The upload of `baseName` once it has been sent to the storage. */
async function upload(flow: Flow, baseName: string): Promise<FakeXhr> {
  let request: FakeXhr | undefined
  await waitFor(() => {
    request = flow.xhr.requests.find((candidate) => candidate.sent && candidate.url.includes(`/doc-${baseName}?`))
    expect(request).toBeDefined()
  })
  return request as FakeXhr
}

async function respond(request: FakeXhr, status = 201) {
  await act(async () => request.respond(status))
}

function patches(flow: Flow) {
  return flow.api.sent('PATCH', PROJECT_PATH)
}

/** The names of the documents in the body of the PATCH at `index`. */
function patchedNames(flow: Flow, index: number): string[] {
  const body = patches(flow)[index]?.body as { documents: DocumentRef[] } | undefined
  return body?.documents.map((ref) => ref.name) ?? []
}

function sheets(flow: Flow) {
  return selectSheets(flow.hook.result.current.state)
}

/** Finishes the open validation run with a result per document; `invalid` ones get an error. */
async function validate(flow: Flow, results: Record<string, 'valid' | 'invalid'>) {
  await waitFor(() => expect(flow.validations.at(-1)).toBeDefined())
  const stream = flow.validations.at(-1)
  await act(async () => {
    Object.entries(results).forEach(([document, result], index, all) => {
      stream?.push({ overallProgress: Math.round(((index + 1) / all.length) * 99), document, documentProgress: 100, error: result === 'invalid' ? 'Mock: kein Finanzbericht erkannt.' : null })
    })
    stream?.push({ overallProgress: 100, document: '' })
    stream?.end()
  })
  await waitFor(() => expect(flow.hook.result.current.state.validation.status).toBe('done'))
}

/** Answers the next `times` requests to the stream `path` with `status`, then streams again as before. */
function refuseStream(flow: Flow, path: string, status: number, times = 1) {
  const streams = path === VALIDATION_PATH ? flow.validations : flow.extractions
  let refused = 0
  flow.api.on('GET', path, () => {
    if (refused < times) {
      refused += 1
      return new Response(null, { status })
    }
    const stream = new FakeEventStream()
    streams.push(stream)
    return stream
  })
}

/** Goes to step `extract` with the valid document `d1` and waits for the extraction stream. */
async function extract(flow: Flow) {
  await loaded(flow)
  await validate(flow, { d1: 'valid' })
  act(() => flow.hook.result.current.actions.advance())
  await waitFor(() => expect(flow.extractions).toHaveLength(1))
}

const POSITION = { name: 'Umsatzerlöse', value: '184 300', period: '2025', source: 'd1 · S. 1', page: 1 }

beforeEach(() => {
  setAccessTokenProvider(async () => 'app-token')
  reconnectWaits.length = 0
})

afterEach(() => {
  setAccessTokenProvider(null)
})

describe('ProjectFlowProvider', () => {
  it('loads the project and checks the documents it already has', async () => {
    const flow = setup([linked('d1')])

    await loaded(flow)
    await validate(flow, { d1: 'valid' })

    expect(sheets(flow).map(({ id, status }) => ({ id, status }))).toEqual([{ id: 'd1', status: 'valid' }])
    expect(flow.api.sent('GET', PROJECT_PATH)[0]?.headers.get('Authorization')).toBe('Bearer app-token')
  })

  it('says when the project does not exist', async () => {
    const api = stubApi()
    api.on('GET', PROJECT_PATH, () => new Response(null, { status: 404 }))

    const { result } = renderHook(() => useProjectFlowState(), {
      wrapper: ({ children }) => <ProjectFlowProvider projectId={PROJECT_ID}>{children}</ProjectFlowProvider>,
    })

    await waitFor(() => expect(result.current.loadError).toBe(PROJECT_NOT_FOUND))
    expect(result.current.project).toBeNull()
  })

  it('AC-19: rejected files cause no request and are named in the message', async () => {
    const flow = setup()
    await loaded(flow)
    const tooLarge = new File(['x'], 'riesig.pdf')
    Object.defineProperty(tooLarge, 'size', { value: 50 * 1024 * 1024 + 1 })

    act(() => flow.hook.result.current.actions.addFiles([new File(['x'], 'notiz.txt'), new File([], 'leer.pdf'), tooLarge, new File(['x'], ' .pdf')]))

    expect(flow.hook.result.current.state.message).toBe(
      'notiz.txt, leer.pdf, riesig.pdf,  .pdf: nur PDF-, Word- oder Excel-Dateien bis 50 MB und mit höchstens 200 Zeichen im Namen.',
    )
    expect(sheets(flow)).toEqual([])
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.api.requests.map((request) => `${request.method} ${request.path}`)).toEqual([`GET ${PROJECT_PATH}`])
    expect(flow.xhr.requests).toHaveLength(0)
  })

  it('AC-3: sends the browser hash to the backend and the file straight to the storage, without Authorization', async () => {
    const flow = setup()
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    const put = await upload(flow, 'bilanz')

    const [urlRequest] = flow.api.sent('POST', `${PROJECT_PATH}/upload-url`)
    expect(urlRequest?.body).toEqual({ sha256: fakeSha256('%PDF bilanz'), name: 'bilanz.pdf', size: 11, contentType: 'application/pdf' })
    expect(urlRequest?.headers.get('Authorization')).toBe('Bearer app-token')
    expect(put.method).toBe('PUT')
    expect(put.headers.has('authorization')).toBe(false)
    expect(put.headers.get('x-ms-blob-type')).toBe('BlockBlob')
  })

  it('AC-14: uploads at most 4 files at a time and shows the progress of each', async () => {
    const flow = setup()
    await loaded(flow)
    const names = ['a', 'b', 'c', 'd', 'e', 'f']

    act(() => flow.hook.result.current.actions.addFiles(names.map((name) => pdf(name))))
    await waitFor(() => expect(flow.xhr.open()).toHaveLength(4))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.xhr.open()).toHaveLength(4)
    expect(flow.api.sent('POST', `${PROJECT_PATH}/upload-url`)).toHaveLength(4)
    expect(sheets(flow).map((sheet) => sheet.status)).toEqual(Array.from(names, () => 'uploading'))

    const first = flow.xhr.open()[0] as FakeXhr
    act(() => first.progress(5, 10))
    expect(sheets(flow).find((sheet) => first.url.includes(`/doc-${sheet.name.replace('.pdf', '')}?`))?.progress).toBe(50)

    await respond(first)
    await waitFor(() => expect(flow.xhr.requests.filter((request) => request.sent)).toHaveLength(5))
    expect(flow.xhr.open()).toHaveLength(4)
  })

  it('AC-4: links all finished uploads with one PATCH once none runs, with all documents and no signed query', async () => {
    const flow = setup([linked('d0')])
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz'), pdf('guv')]))
    await respond(await upload(flow, 'bilanz'))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(patches(flow)).toHaveLength(0)
    await respond(await upload(flow, 'guv'))

    await waitFor(() => expect(flow.hook.result.current.state.uploads).toEqual({}))
    expect(patches(flow)).toHaveLength(1)
    const [patch] = patches(flow)
    expect(patch?.headers.get('Content-Type')).toBe('application/json')
    expect(patch?.body).toEqual({
      documents: [
        linked('d0'),
        { url: documentUrl('doc-bilanz'), name: 'bilanz.pdf', size: 11, contentType: 'application/pdf' },
        { url: documentUrl('doc-guv'), name: 'guv.pdf', size: 8, contentType: 'application/pdf' },
      ],
    })
    expect(sheets(flow).map(({ id, status }) => ({ id, status }))).toEqual([
      { id: 'd0', status: 'queued' },
      { id: 'doc-bilanz', status: 'queued' },
      { id: 'doc-guv', status: 'queued' },
    ])
  })

  it('AC-4: a linked sheet keeps the React key of its upload', async () => {
    const flow = setup()
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    const keyWhileUploading = sheets(flow)[0]?.key
    await respond(await upload(flow, 'bilanz'))
    await waitFor(() => expect(sheets(flow)[0]?.documentId).toBe('doc-bilanz'))

    expect(sheets(flow)[0]?.key).toBe(keyWhileUploading)
  })

  it('AC-16: a failed upload is never linked', async () => {
    const flow = setup()
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('kaputt'), pdf('bilanz')]))
    await respond(await upload(flow, 'kaputt'), 500)
    await respond(await upload(flow, 'bilanz'))

    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    expect(patchedNames(flow, 0)).toEqual(['bilanz.pdf'])
    await waitFor(() => expect(sheets(flow).find((sheet) => sheet.name === 'kaputt.pdf')).toMatchObject({ status: 'failed', error: UPLOAD_FAILED }))
  })

  it('AC-7: opens the validation stream again after each PATCH and shows each document\'s result', async () => {
    const flow = setup()
    await loaded(flow)
    expect(flow.validations).toHaveLength(0)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await respond(await upload(flow, 'bilanz'))
    await waitFor(() => expect(flow.validations).toHaveLength(1))
    await act(async () => flow.validations[0]?.push({ overallProgress: 50, document: 'doc-bilanz', documentProgress: 50 }))
    await waitFor(() => expect(sheets(flow)[0]).toMatchObject({ status: 'checking', progress: 50 }))

    act(() => flow.hook.result.current.actions.addFiles([pdf('protokoll')]))
    await respond(await upload(flow, 'protokoll'))
    await waitFor(() => expect(flow.validations).toHaveLength(2))
    expect(flow.validations[0]?.cancelled).toBe(true)
    await validate(flow, { 'doc-bilanz': 'valid', 'doc-protokoll': 'invalid' })

    expect(sheets(flow).map(({ id, status, error }) => ({ id, status, error }))).toEqual([
      { id: 'doc-bilanz', status: 'valid', error: null },
      { id: 'doc-protokoll', status: 'invalid', error: 'Mock: kein Finanzbericht erkannt.' },
    ])
    expect(patches(flow)).toHaveLength(2)
  })

  it('links a duplicate the tenant already has without uploading it', async () => {
    const flow = setup()
    const existing = { url: 'https://store.example/tenant/other-project/doc-alt', name: 'bilanz.pdf', size: 11, contentType: 'application/pdf' }
    flow.api.on('POST', `${PROJECT_PATH}/upload-url`, () => json({ document: existing }))
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))

    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    expect(patches(flow)[0]?.body).toEqual({ documents: [existing] })
    expect(flow.xhr.requests).toHaveLength(0)
    await waitFor(() => expect(sheets(flow).map((sheet) => sheet.id)).toEqual(['doc-alt']))
  })

  it('matches an upload the backend replaced by its duplicate by name and size', async () => {
    const flow = setup()
    const duplicate = { url: 'https://store.example/tenant/other-project/doc-alt', name: 'bilanz.pdf', size: 11, contentType: 'application/pdf' }
    flow.backend.patch = () => json({ ...flow.backend.project, documents: [duplicate] })
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    const key = sheets(flow)[0]?.key
    await respond(await upload(flow, 'bilanz'))

    await waitFor(() => expect(flow.hook.result.current.state.uploads).toEqual({}))
    expect(sheets(flow).map(({ key: sheetKey, id, status }) => ({ key: sheetKey, id, status }))).toEqual([{ key, id: 'doc-alt', status: 'queued' }])
  })

  it('fails only the uploads a PATCH rejected and links the others with the next PATCH', async () => {
    const flow = setup()
    flow.backend.patch = () => {
      flow.backend.patch = undefined
      return validationProblem({ 'documents[1].size': ['does not match the uploaded file'] })
    }
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz'), pdf('guv')]))
    await respond(await upload(flow, 'bilanz'))
    await respond(await upload(flow, 'guv'))

    await waitFor(() => expect(patches(flow)).toHaveLength(2))
    expect(patchedNames(flow, 1)).toEqual(['bilanz.pdf'])
    await waitFor(() => expect(sheets(flow).map(({ name, status, error }) => ({ name, status, error }))).toEqual([
      { name: 'bilanz.pdf', status: 'queued', error: null },
      { name: 'guv.pdf', status: 'failed', error: NOT_LINKED },
    ]))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(patches(flow)).toHaveLength(2)
  })

  it('sends PATCH and DELETE one after another', async () => {
    const flow = setup([linked('d0')])
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => patchAnswer.promise
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await respond(await upload(flow, 'bilanz'))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    act(() => flow.hook.result.current.actions.removeDocument('d0'))

    expect(sheets(flow).map((sheet) => sheet.id)).not.toContain('d0')
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.api.sent('DELETE', `${PROJECT_PATH}/document/d0`)).toHaveLength(0)

    patchAnswer.resolve(json({ ...flow.backend.project, documents: [linked('d0'), linked('doc-bilanz', 'bilanz.pdf', 11)] }))
    await waitFor(() => expect(flow.api.sent('DELETE', `${PROJECT_PATH}/document/d0`)).toHaveLength(1))
    await waitFor(() => expect(flow.hook.result.current.state.project?.documents.map((ref) => ref.name)).toEqual(['bilanz.pdf']))
    const order = flow.api.requests.filter((request) => request.method === 'PATCH' || request.method === 'DELETE').map((request) => request.method)
    expect(order).toEqual(['PATCH', 'DELETE'])
  })

  it('links the uploads a failed PATCH did not reject, also when the rejected one was removed meanwhile', async () => {
    const flow = setup()
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => {
      flow.backend.patch = undefined
      return patchAnswer.promise
    }
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz'), pdf('guv')]))
    await respond(await upload(flow, 'bilanz'))
    await respond(await upload(flow, 'guv'))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    act(() => flow.hook.result.current.actions.removeDocument(sheets(flow).find((sheet) => sheet.name === 'bilanz.pdf')?.id ?? ''))
    await act(async () => patchAnswer.resolve(validationProblem({ 'documents[0].size': ['does not match the uploaded file'] })))

    await waitFor(() => expect(patches(flow)).toHaveLength(2))
    expect(patchedNames(flow, 1)).toEqual(['guv.pdf'])
    await waitFor(() => expect(sheets(flow).map(({ id, status }) => ({ id, status }))).toEqual([{ id: 'doc-guv', status: 'queued' }]))
  })

  it('unlinks a new document whose upload the user removed while its PATCH ran', async () => {
    const flow = setup()
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => patchAnswer.promise
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await respond(await upload(flow, 'bilanz'))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    act(() => flow.hook.result.current.actions.removeDocument(sheets(flow)[0]?.id ?? ''))
    await act(async () => patchAnswer.resolve(json({ ...flow.backend.project, documents: [linked('doc-bilanz', 'bilanz.pdf', 11)] })))

    await waitFor(() => expect(flow.api.sent('DELETE', `${PROJECT_PATH}/document/doc-bilanz`)).toHaveLength(1))
    await waitFor(() => expect(flow.hook.result.current.state.project?.documents).toEqual([]))
    expect(sheets(flow)).toEqual([])
  })

  it('keeps a document the project had when the user removes its re-added copy while the PATCH runs', async () => {
    const bilanz = linked('d0', 'bilanz.pdf', 11)
    const flow = setup([bilanz])
    flow.api.on('POST', `${PROJECT_PATH}/upload-url`, () => json({ document: bilanz }))
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => patchAnswer.promise
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    act(() => flow.hook.result.current.actions.removeDocument(sheets(flow).find((sheet) => sheet.documentId === null)?.id ?? ''))
    await act(async () => patchAnswer.resolve(json(flow.backend.project)))

    await waitFor(() => expect(flow.validations).toHaveLength(2))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.api.sent('DELETE', new RegExp(`^${PROJECT_PATH}/document/`))).toHaveLength(0)
    expect(flow.hook.result.current.state.project?.documents).toEqual([bilanz])
    expect(sheets(flow).map((sheet) => sheet.id)).toEqual(['d0'])
  })

  it('keeps a file added twice when the user removes one copy while the PATCH runs', async () => {
    const flow = setup()
    let issued = 0
    flow.api.on('POST', `${PROJECT_PATH}/upload-url`, () => {
      issued += 1
      return json({ blobUrl: `${documentUrl(`doc-copy${issued}`)}?sig=secret`, expires: EXPIRES })
    })
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => patchAnswer.promise
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz'), pdf('bilanz')]))
    await respond(await upload(flow, 'copy1'))
    await respond(await upload(flow, 'copy2'))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    // The copy whose URL the backend keeps; it links that document for the other copy too, as the same file.
    const first = Object.values(flow.hook.result.current.state.uploads).find((item) => item.ref?.url.includes('/doc-copy1'))
    act(() => flow.hook.result.current.actions.removeDocument(first?.localKey ?? ''))
    const kept = { url: documentUrl('doc-copy1'), name: 'bilanz.pdf', size: 11, contentType: 'application/pdf' }
    await act(async () => patchAnswer.resolve(json({ ...flow.backend.project, documents: [kept] })))

    await waitFor(() => expect(flow.hook.result.current.state.uploads).toEqual({}))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.api.sent('DELETE', new RegExp(`^${PROJECT_PATH}/document/`))).toHaveLength(0)
    expect(sheets(flow).map(({ id, status }) => ({ id, status }))).toEqual([{ id: 'doc-copy1', status: 'queued' }])
  })

  it('removing a running upload stops it and links nothing', async () => {
    const flow = setup()
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    const put = await upload(flow, 'bilanz')
    act(() => flow.hook.result.current.actions.removeDocument(sheets(flow)[0]?.id ?? ''))

    expect(put.aborted).toBe(true)
    expect(sheets(flow)).toEqual([])
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(patches(flow)).toHaveLength(0)
  })

  it('AC-24: advance removes every invalid document, then reads the valid ones in step extract', async () => {
    const flow = setup([linked('d1'), linked('d2'), linked('d3')])
    await loaded(flow)
    await validate(flow, { d1: 'valid', d2: 'invalid', d3: 'invalid' })
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(true)

    act(() => flow.hook.result.current.actions.advance())

    await waitFor(() => expect(flow.hook.result.current.state.step).toBe('extract'))
    expect(flow.api.requests.filter((request) => request.method === 'DELETE').map((request) => request.path)).toEqual([
      `${PROJECT_PATH}/document/d2`,
      `${PROJECT_PATH}/document/d3`,
    ])
    expect(flow.hook.result.current.state.project?.documents.map((ref) => ref.url)).toEqual([documentUrl('d1')])
    await waitFor(() => expect(flow.extractions).toHaveLength(1))
    await act(async () => {
      flow.extractions[0]?.push({ overallProgress: 50, document: 'd1', pages: 2, pagesRead: 1, positions: 2, position: { name: 'Umsatzerlöse', value: '184 300', period: '2025', source: 'd1 · S. 1', page: 1 } })
    })
    await waitFor(() => expect(selectExtractionLines(flow.hook.result.current.state)[0]).toMatchObject({ documentId: 'd1', pagesRead: 1, track: { kind: 'segments', segments: ['done', 'now'] } }))
    await act(async () => {
      flow.extractions[0]?.push({ overallProgress: 100, document: 'd1', pagesRead: 2, positions: 4 })
      flow.extractions[0]?.end()
    })
    await waitFor(() => expect(flow.hook.result.current.state.extraction).toMatchObject({ status: 'done', positions: 4 }))
    expect(flow.hook.result.current.state.extraction.found).toHaveLength(1)
  })

  it('AC-25: stays with a message when no valid document remains', async () => {
    const flow = setup([linked('d1')])
    await loaded(flow)
    await validate(flow, { d1: 'invalid' })

    act(() => flow.hook.result.current.actions.advance())

    await waitFor(() => expect(flow.hook.result.current.state.message).toBe(NO_VALID_DOCUMENT))
    expect(flow.hook.result.current.state).toMatchObject({ step: 'upload', advancing: false })
    expect(flow.api.sent('DELETE', `${PROJECT_PATH}/document/d1`)).toHaveLength(1)
    expect(sheets(flow)).toEqual([])
    expect(flow.extractions).toHaveLength(0)
  })

  it('aborts uploads, requests and streams on unmount', async () => {
    const flow = setup([linked('d1')])
    const patchAnswer = deferred<Response>()
    flow.backend.patch = () => patchAnswer.promise
    await loaded(flow)
    await waitFor(() => expect(flow.validations).toHaveLength(1))
    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await respond(await upload(flow, 'bilanz'))
    await waitFor(() => expect(patches(flow)).toHaveLength(1))
    act(() => flow.hook.result.current.actions.addFiles([pdf('guv')]))
    const put = await upload(flow, 'guv')

    flow.hook.unmount()

    expect(put.aborted).toBe(true)
    expect(patches(flow)[0]?.signal?.aborted).toBe(true)
    await waitFor(() => expect(flow.validations[0]?.cancelled).toBe(true))
    expect(flow.api.sent('GET', `${PROJECT_PATH}/document-validation/sse`)[0]?.signal?.aborted).toBe(true)
  })

  it('works under StrictMode: one PATCH per batch and one live validation stream', async () => {
    const flow = setup([], { strict: true })
    await loaded(flow)

    act(() => flow.hook.result.current.actions.addFiles([pdf('bilanz')]))
    await respond(await upload(flow, 'bilanz'))
    await validate(flow, { 'doc-bilanz': 'valid' })

    expect(patches(flow)).toHaveLength(1)
    expect(flow.validations.filter((stream) => !stream.cancelled)).toHaveLength(1)
    expect(sheets(flow).map(({ id, status }) => ({ id, status }))).toEqual([{ id: 'doc-bilanz', status: 'valid' }])
  })
})

describe('ProjectFlowProvider stream breaks', () => {
  it('reconnects a validation stream that closes early or answers 503, within the same run', async () => {
    const flow = setup([linked('d1'), linked('d2')])
    await loaded(flow)
    await waitFor(() => expect(flow.validations).toHaveLength(1))
    await act(async () => flow.validations[0]?.push({ overallProgress: 50, document: 'd1', documentProgress: 100 }))
    await waitFor(() => expect(sheets(flow)[0]?.status).toBe('valid'))
    refuseStream(flow, VALIDATION_PATH, 503)

    await act(async () => flow.validations[0]?.end())
    await waitFor(() => expect(flow.validations).toHaveLength(2))
    expect(flow.hook.result.current.state.validation).toMatchObject({ run: 1, status: 'running' })
    await validate(flow, { d1: 'valid', d2: 'valid' })

    expect(flow.api.sent('GET', VALIDATION_PATH)).toHaveLength(3)
    expect(reconnectWaits).toEqual([1000, 3000])
    expect(flow.hook.result.current.state.validation.run).toBe(1)
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(true)
  })

  it('keeps documents without a result failed after the last reconnect, and advancing stays blocked', async () => {
    const flow = setup([linked('d1'), linked('d2')])
    await loaded(flow)
    await waitFor(() => expect(flow.validations).toHaveLength(1))
    await act(async () => flow.validations[0]?.push({ overallProgress: 50, document: 'd1', documentProgress: 100 }))
    await waitFor(() => expect(sheets(flow)[0]?.status).toBe('valid'))

    for (let index = 0; index < 4; index++) {
      await waitFor(() => expect(flow.validations).toHaveLength(index + 1))
      await act(async () => flow.validations[index]?.end())
    }

    await waitFor(() => expect(flow.hook.result.current.state.validation).toMatchObject({ status: 'failed', error: CHECK_INTERRUPTED }))
    expect(reconnectWaits).toEqual([1000, 3000, 10_000])
    expect(sheets(flow).map(({ id, status, error }) => ({ id, status, error }))).toEqual([
      { id: 'd1', status: 'valid', error: null },
      { id: 'd2', status: 'failed', error: CHECK_INTERRUPTED },
    ])
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(false)
    expect(selectCanRetryValidation(flow.hook.result.current.state)).toBe(true)

    act(() => flow.hook.result.current.actions.advance())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.hook.result.current.state).toMatchObject({ step: 'upload', advancing: false })
    expect(flow.api.sent('DELETE', new RegExp(`^${PROJECT_PATH}/document/`))).toHaveLength(0)
    expect(flow.api.sent('GET', VALIDATION_PATH)).toHaveLength(4)
  })

  it.each([401, 404])('does not reconnect when the backend answers %i', async (status) => {
    const flow = setup([linked('d1')])
    refuseStream(flow, VALIDATION_PATH, status)

    await loaded(flow)

    await waitFor(() => expect(flow.hook.result.current.state.validation).toMatchObject({ status: 'failed', error: CHECK_FAILED }))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.api.sent('GET', VALIDATION_PATH)).toHaveLength(1)
    expect(reconnectWaits).toEqual([])
    expect(sheets(flow)[0]).toMatchObject({ status: 'failed', error: CHECK_FAILED })
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(false)
  })

  it('retryValidation reopens the validation stream after a run error and clears the failure', async () => {
    const flow = setup([linked('d1')])
    await loaded(flow)
    await waitFor(() => expect(flow.validations).toHaveLength(1))
    await act(async () => {
      flow.validations[0]?.push({ overallProgress: 100, document: '', error: 'Analyse nicht verfügbar' })
      flow.validations[0]?.end()
    })
    await waitFor(() => expect(sheets(flow)[0]).toMatchObject({ status: 'failed', error: 'Analyse nicht verfügbar' }))
    // A run error is final: no reconnect.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(flow.validations).toHaveLength(1)
    expect(reconnectWaits).toEqual([])
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(false)
    expect(selectCanRetryValidation(flow.hook.result.current.state)).toBe(true)

    act(() => flow.hook.result.current.actions.retryValidation())
    act(() => flow.hook.result.current.actions.retryValidation())

    expect(flow.hook.result.current.state.validation).toMatchObject({ run: 2, status: 'running', error: null })
    expect(sheets(flow)[0]).toMatchObject({ status: 'queued', error: null })
    expect(selectCanRetryValidation(flow.hook.result.current.state)).toBe(false)
    await waitFor(() => expect(flow.validations).toHaveLength(2))
    await validate(flow, { d1: 'valid' })
    expect(flow.validations).toHaveLength(2)
    expect(sheets(flow)[0]).toMatchObject({ status: 'valid', error: null })
    expect(selectCanAdvance(flow.hook.result.current.state)).toBe(true)
  })

  it('starts the extraction progress over when its stream reconnects, so no position is counted twice', async () => {
    const flow = setup([linked('d1')])
    await extract(flow)
    await act(async () => flow.extractions[0]?.push({ overallProgress: 50, document: 'd1', pages: 2, pagesRead: 1, positions: 1, position: POSITION }))
    await waitFor(() => expect(flow.hook.result.current.state.extraction.found).toHaveLength(1))

    await act(async () => flow.extractions[0]?.fail())
    await waitFor(() => expect(flow.extractions).toHaveLength(2))
    expect(flow.hook.result.current.state.extraction).toMatchObject({ run: 1, status: 'running', found: [], positions: 0, documents: {} })
    await act(async () => {
      flow.extractions[1]?.push({ overallProgress: 50, document: 'd1', pages: 2, pagesRead: 1, positions: 1, position: POSITION })
      flow.extractions[1]?.push({ overallProgress: 100, document: 'd1', pagesRead: 2, positions: 1 })
      flow.extractions[1]?.end()
    })

    await waitFor(() => expect(flow.hook.result.current.state.extraction).toMatchObject({ status: 'done', positions: 1 }))
    expect(flow.hook.result.current.state.extraction.found).toEqual([{ ...POSITION, documentId: 'd1' }])
    expect(reconnectWaits).toEqual([1000])
  })

  it('fails the extraction after the last reconnect; retryExtraction restarts it and clears the failure', async () => {
    const flow = setup([linked('d1')])
    await extract(flow)
    refuseStream(flow, EXTRACTION_PATH, 503, 3)

    await act(async () => flow.extractions[0]?.fail())

    await waitFor(() => expect(flow.hook.result.current.state.extraction).toMatchObject({ run: 1, status: 'failed', error: EXTRACTION_FAILED }))
    expect(flow.api.sent('GET', EXTRACTION_PATH)).toHaveLength(4)
    expect(reconnectWaits).toEqual([1000, 3000, 10_000])
    expect(selectCanRetryExtraction(flow.hook.result.current.state)).toBe(true)

    act(() => flow.hook.result.current.actions.retryExtraction())

    expect(flow.hook.result.current.state.extraction).toMatchObject({ run: 2, status: 'running', error: null })
    expect(selectCanRetryExtraction(flow.hook.result.current.state)).toBe(false)
    await waitFor(() => expect(flow.extractions).toHaveLength(2))
    await act(async () => {
      flow.extractions[1]?.push({ overallProgress: 100, document: 'd1', pages: 1, pagesRead: 1, positions: 1, position: POSITION })
      flow.extractions[1]?.end()
    })
    await waitFor(() => expect(flow.hook.result.current.state.extraction).toMatchObject({ run: 2, status: 'done', error: null }))
    expect(flow.hook.result.current.state.extraction.found).toEqual([{ ...POSITION, documentId: 'd1' }])
  })
})
