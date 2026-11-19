import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BlobUploadError } from '../../api/blobStorage/index.ts'
import { json, stubApi } from '../../test/fakeApi.ts'
import { fakeSha256, stubDigest } from '../../test/fakeCrypto.ts'
import { stubXhr, type FakeXhr } from '../../test/fakeXhr.ts'
import { sha256Hex, uploadDocument } from './uploadDocument.ts'

const NOW = Date.parse('2026-11-19T10:00:00Z')
const LATER = new Date(NOW + 15 * 60_000).toISOString()
const EARLIER = new Date(NOW - 1_000).toISOString()
const CONTENT = '%PDF-1.7 Jahresabschluss'

function blobUrl(n: number) {
  return `https://store.example/tenant/p1/doc-${n}?sv=2025-01-05&sr=b&sp=c&sig=signature-${n}`
}

function pdf(name = 'Jahresabschluss.pdf') {
  // No type from the browser: the content type comes from the extension.
  return new File([CONTENT], name)
}

/** Answers the n-th upload-url request with the n-th entry. */
function stubUploadUrls(...answers: Array<{ expires: string } | { document: object }>) {
  const api = stubApi()
  let count = 0
  api.on('POST', '/project/p1/upload-url', () => {
    const answer = answers[count] ?? answers[answers.length - 1]
    count++
    return json('expires' in answer ? { blobUrl: blobUrl(count), expires: answer.expires } : answer)
  })
  return api
}

async function nextUpload(xhr: ReturnType<typeof stubXhr>, index: number): Promise<FakeXhr> {
  await vi.waitFor(() => expect(xhr.requests[index]?.sent).toBe(true))
  return xhr.requests[index] as FakeXhr
}

beforeEach(() => {
  stubDigest()
})

describe('sha256Hex', () => {
  it('hashes the bytes with crypto.subtle and writes 64 lower-case hex digits', async () => {
    const digest = stubDigest()

    await expect(sha256Hex(new Blob(['AB']))).resolves.toBe(`4142${'0'.repeat(60)}`)
    expect(digest).toHaveBeenCalledWith('SHA-256', expect.anything())
  })
})

describe('uploadDocument', () => {
  it('AC-1: asks for an upload URL with SHA-256, name, size and content type, uploads, and returns the ref without the signed query', async () => {
    const api = stubUploadUrls({ expires: LATER })
    const xhr = stubXhr()
    const progress: number[] = []

    const result = uploadDocument('p1', pdf(), { now: () => NOW, onProgress: (percent) => progress.push(percent) })
    const put = await nextUpload(xhr, 0)
    put.progress(12, 24)
    put.respond(201)

    await expect(result).resolves.toEqual({
      url: 'https://store.example/tenant/p1/doc-1',
      name: 'Jahresabschluss.pdf',
      size: CONTENT.length,
      contentType: 'application/pdf',
    })
    expect(api.sent('POST', '/project/p1/upload-url')[0]?.body).toEqual({
      sha256: fakeSha256(CONTENT),
      name: 'Jahresabschluss.pdf',
      size: CONTENT.length,
      contentType: 'application/pdf',
    })
    expect(put.url).toBe(blobUrl(1))
    expect(put.headers.get('content-type')).toBe('application/pdf')
    expect(progress).toEqual([0, 50, 100])
  })

  it('skips the upload for a duplicate and returns the existing document', async () => {
    const existing = { url: 'https://store.example/tenant/other/doc-9', name: 'Jahresabschluss.pdf', size: CONTENT.length, contentType: 'application/pdf' }
    stubUploadUrls({ document: existing })
    const xhr = stubXhr()

    await expect(uploadDocument('p1', pdf(), { now: () => NOW })).resolves.toEqual(existing)
    expect(xhr.requests).toHaveLength(0)
  })

  it('AC-18: gets a new URL without uploading when the first one had already expired', async () => {
    const api = stubUploadUrls({ expires: EARLIER }, { expires: LATER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).respond(201)

    await expect(result).resolves.toMatchObject({ url: 'https://store.example/tenant/p1/doc-2' })
    expect(api.sent('POST', '/project/p1/upload-url')).toHaveLength(2)
    expect(xhr.requests.map((request) => request.url)).toEqual([blobUrl(2)])
  })

  it.each([401, 403])('AC-18: tries once more with a new URL when the storage answers %i', async (status) => {
    stubUploadUrls({ expires: LATER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).respond(status)
    ;(await nextUpload(xhr, 1)).respond(201)

    await expect(result).resolves.toMatchObject({ url: 'https://store.example/tenant/p1/doc-2' })
    expect(xhr.requests.map((request) => request.url)).toEqual([blobUrl(1), blobUrl(2)])
  })

  it('AC-18: tries once more when no answer came before the file had fully gone out', async () => {
    stubUploadUrls({ expires: LATER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).failNetwork()
    ;(await nextUpload(xhr, 1)).respond(201)

    await expect(result).resolves.toMatchObject({ url: 'https://store.example/tenant/p1/doc-2' })
  })

  it('AC-18: fails without another try when the answer is lost after the file had gone out', async () => {
    const api = stubUploadUrls({ expires: LATER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).failNetwork({ afterBody: true })

    await expect(result).rejects.toEqual(new BlobUploadError(0, false))
    expect(api.sent('POST', '/project/p1/upload-url')).toHaveLength(1)
  })

  it('AC-18: tries only once more', async () => {
    const api = stubUploadUrls({ expires: LATER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).respond(403)
    ;(await nextUpload(xhr, 1)).respond(403)

    await expect(result).rejects.toMatchObject({ status: 403, rejected: true })
    expect(api.sent('POST', '/project/p1/upload-url')).toHaveLength(2)
    expect(xhr.requests).toHaveLength(2)
  })

  it('AC-17: never checks the expiry once the upload has started', async () => {
    const api = stubUploadUrls({ expires: new Date(NOW + 1_000).toISOString() })
    const xhr = stubXhr()
    let clock = NOW

    const result = uploadDocument('p1', pdf(), { now: () => clock })
    const put = await nextUpload(xhr, 0)
    clock = NOW + 20 * 60_000
    put.respond(201)

    await expect(result).resolves.toMatchObject({ url: 'https://store.example/tenant/p1/doc-1' })
    expect(api.sent('POST', '/project/p1/upload-url')).toHaveLength(1)
  })

  it('AC-18: leaves the last try to the storage even if the clock says its URL has expired', async () => {
    stubUploadUrls({ expires: EARLIER })
    const xhr = stubXhr()

    const result = uploadDocument('p1', pdf(), { now: () => NOW })
    ;(await nextUpload(xhr, 0)).respond(201)

    await expect(result).resolves.toMatchObject({ url: 'https://store.example/tenant/p1/doc-2' })
  })

  it('does not retry a failed upload-url request', async () => {
    const api = stubApi()
    api.on('POST', '/project/p1/upload-url', () => new Response(null, { status: 404 }))
    const xhr = stubXhr()

    await expect(uploadDocument('p1', pdf(), { now: () => NOW })).rejects.toMatchObject({ status: 404 })
    expect(xhr.requests).toHaveLength(0)
  })

  it('stops before any request when the signal has already aborted', async () => {
    const api = stubUploadUrls({ expires: LATER })
    const controller = new AbortController()
    controller.abort()

    await expect(uploadDocument('p1', pdf(), { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    expect(api.requests).toHaveLength(0)
  })
})
